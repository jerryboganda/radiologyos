"""Redis token buckets per user and per tenant on expensive endpoints (ADR 0032).

One Lua script refills and takes from both buckets atomically, so a request
denied by the tenant bucket does not spend the user's tokens. Keys begin with
the tenant id (hard rule 7) and hold two numbers; they expire once a bucket
would be full again. A denied request gets 429 with ``Retry-After``. When Redis
is unreachable the limiter fails open: the request proceeds, the outage is
logged once, and Redis is not retried for ``COOLDOWN_S``.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from apps.api.app.core.config import BucketRule, RateRule, get_settings
from apps.api.app.security.principal import Principal
from fastapi import Depends, HTTPException, status
from packages.observability.metrics import Counter

log = logging.getLogger("radbrain.api")
COOLDOWN_S = 30.0
RATE_LIMITED = Counter("radbrain_rate_limited_total",
                       "Requests refused by a rate limit.", ("bucket",))
# KEYS: user bucket, tenant bucket. ARGV: user rate/s, user burst, tenant rate/s,
# tenant burst, now (s), cost. Returns {allowed, retry_after_seconds}.
SCRIPT = """
local function refill(key, rate, burst, now)
  local data = redis.call('HMGET', key, 'tokens', 'ts')
  local tokens = tonumber(data[1]) or burst
  local ts = tonumber(data[2]) or now
  return math.min(burst, tokens + math.max(0, now - ts) * rate)
end
local now = tonumber(ARGV[5])
local cost = tonumber(ARGV[6])
local rates = {tonumber(ARGV[1]), tonumber(ARGV[3])}
local bursts = {tonumber(ARGV[2]), tonumber(ARGV[4])}
local tokens = {}
local wait = 0
for i = 1, 2 do
  tokens[i] = refill(KEYS[i], rates[i], bursts[i], now)
  if tokens[i] < cost then wait = math.max(wait, (cost - tokens[i]) / rates[i]) end
end
local allowed = 0
if wait == 0 then
  allowed = 1
  for i = 1, 2 do tokens[i] = tokens[i] - cost end
end
for i = 1, 2 do
  redis.call('HSET', KEYS[i], 'tokens', tostring(tokens[i]), 'ts', tostring(now))
  redis.call('EXPIRE', KEYS[i], math.ceil(bursts[i] / rates[i]) + 60)
end
return {allowed, tostring(wait)}
"""


def bucket_keys(bucket: str, tenant_id: UUID, user_id: UUID) -> list[str]:
    return [f"{tenant_id}:ratelimit:{bucket}:user:{user_id}",
            f"{tenant_id}:ratelimit:{bucket}:tenant"]


def script_args(rule: BucketRule, now: float, cost: float = 1.0) -> list[str]:
    def pair(r: RateRule) -> list[str]:
        return [repr(r.per_minute / 60.0), str(r.burst)]

    return [*pair(rule.user), *pair(rule.tenant), repr(now), repr(cost)]


class RateLimiter:
    def __init__(self, client_factory: Callable[[], Any],
                 clock: Callable[[], float] = time.time) -> None:
        self._factory = client_factory
        self._client: Any = None
        self._clock = clock
        self._down_until = 0.0
        self._warned = False

    async def retry_after(self, bucket: str, rule: BucketRule, tenant_id: UUID,
                          user_id: UUID) -> float | None:
        """Seconds to wait when refused, None when allowed (or Redis is down)."""
        if time.monotonic() < self._down_until:
            return None
        try:
            if self._client is None:
                self._client = self._factory()
            keys = bucket_keys(bucket, tenant_id, user_id)
            allowed, wait = await self._client.eval(SCRIPT, 2, *keys,
                                                    *script_args(rule, self._clock()))
        except Exception as exc:  # fail open by design (ADR 0032)
            self._down_until = time.monotonic() + COOLDOWN_S
            if not self._warned:
                self._warned = True
                log.warning("rate_limit_unavailable", extra={"error_type": type(exc).__name__})
            return None
        self._warned = False
        return None if int(allowed) == 1 else max(float(wait), 0.001)


def _redis_client() -> Any:
    import redis.asyncio as redis_asyncio

    return redis_asyncio.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.25,
                                        socket_timeout=0.5)


_limiter: list[RateLimiter] = [RateLimiter(_redis_client)]


def set_limiter(limiter: RateLimiter | None) -> None:
    _limiter[0] = limiter or RateLimiter(_redis_client)


def rate_limit(bucket: str, principal_dependency: Any) -> Callable[..., Any]:
    """A route dependency enforcing ``bucket`` for the request's principal."""

    async def enforce(principal: Principal = Depends(principal_dependency)) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        wait = await _limiter[0].retry_after(bucket, settings.rate_rule(bucket),
                                             principal.tenant_id, principal.user_id)
        if wait is None:
            return
        RATE_LIMITED.inc(bucket)
        log.info("rate_limited", extra={"bucket": bucket,
                                        "tenant_id": str(principal.tenant_id)})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests; try again shortly.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )

    enforce.__name__ = f"rate_limit_{bucket}"
    return enforce
