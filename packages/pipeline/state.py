"""Library pipeline pause state, shared by every worker process (ADR 0037).

Two reasons stop model work between units (a page, a figure page, a knowledge
chunk); each unit's result is already saved, so work resumes exactly where it
stopped:

* ``manual`` - the owner paused processing (CLI or Settings). It stays paused
  until resumed; queued tasks re-check every few minutes.
* ``quota`` - a provider's usage window ran out (the ChatGPT 5-hour quota).
  The pause ends by itself at the reset time the provider gave (or after a
  default wait); the first process to hit it is told so it can alert the owner.

State lives in Redis (the broker every worker already uses). Without
``REDIS_URL`` (unit tests, local tools) nothing is ever paused.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

MANUAL_KEY = "radbrain:pipeline:paused"
QUOTA_KEY = "radbrain:pipeline:quota"
DEFAULT_QUOTA_WAIT_S = 30 * 60
QUOTA_MARGIN_S = 120  # resume a little after the provider's reset time
MANUAL_RECHECK_S = 5 * 60


@dataclass(frozen=True, slots=True)
class PauseState:
    reason: str | None  # None | "manual" | "quota"
    until: float | None = None  # epoch seconds, for a quota pause
    provider: str | None = None

    @property
    def paused(self) -> bool:
        return self.reason is not None

    def recheck_in(self, now: float | None = None) -> int:
        """Seconds a deferred task should wait before trying again."""
        if self.reason == "quota" and self.until is not None:
            return max(60, int(self.until - (now or time.time())))
        return MANUAL_RECHECK_S


@lru_cache(maxsize=1)
def _client() -> Any:
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    import redis

    return redis.Redis.from_url(url, socket_timeout=5, decode_responses=True)


def current(client: Any | None = None) -> PauseState:
    """Manual pause wins; then an active quota pause; else running."""
    r = client if client is not None else _client()
    if r is None:
        return PauseState(None)
    try:
        manual, quota = r.get(MANUAL_KEY), r.hgetall(QUOTA_KEY)
    except Exception:  # an unreachable Redis never blocks work (the broker is down anyway)
        return PauseState(None)
    if manual:
        return PauseState("manual")
    if quota and float(quota.get("until", 0)) > time.time():
        return PauseState("quota", float(quota["until"]), quota.get("provider"))
    return PauseState(None)


def set_manual(paused: bool, client: Any | None = None) -> None:
    r = client if client is not None else _client()
    if r is None:
        return
    if paused:
        r.set(MANUAL_KEY, str(int(time.time())))
    else:
        r.delete(MANUAL_KEY)


def quota_hit(provider: str, retry_after_s: int | None, client: Any | None = None) -> float | None:
    """Record a quota pause; returns its end time only for the first process to hit it.

    Later hits inside the same pause return None, so the owner is alerted once.
    """
    r = client if client is not None else _client()
    if r is None:
        return None
    until = time.time() + (retry_after_s or DEFAULT_QUOTA_WAIT_S) + QUOTA_MARGIN_S
    ttl = int(until - time.time()) + 60
    if not r.set(f"{QUOTA_KEY}:lock", provider, nx=True, ex=ttl):
        return None
    r.hset(QUOTA_KEY, mapping={"until": str(until), "provider": provider})
    r.expire(QUOTA_KEY, ttl)
    return until


def clear_quota(client: Any | None = None) -> None:
    """Lift a quota pause early (the owner knows the window has reset)."""
    r = client if client is not None else _client()
    if r is not None:
        r.delete(QUOTA_KEY, f"{QUOTA_KEY}:lock")
