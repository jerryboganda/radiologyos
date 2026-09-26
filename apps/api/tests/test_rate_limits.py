"""Per-user and per-tenant token buckets with a fake Redis (ADR 0032)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import study
from apps.api.app.core.config import BucketRule, RateRule, get_settings
from apps.api.app.main import app
from apps.api.app.ops import ratelimit
from apps.api.app.security.principal import Principal
from apps.api.tests.study_fakes import MemoryStudyRepo
from fastapi.testclient import TestClient

TENANT = UUID("20000000-0000-4000-8000-000000000001")
USER = UUID("10000000-0000-4000-8000-000000000001")
OTHER = UUID("10000000-0000-4000-8000-000000000002")


class FakeRedis:
    """Runs a Python mirror of the Lua script against in-memory hashes."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, float]] = {}
        self.ttl: dict[str, int] = {}

    async def eval(self, script: str, numkeys: int, *args: str) -> list[Any]:
        assert script == ratelimit.SCRIPT and numkeys == 2
        keys, argv = args[:2], [float(a) for a in args[2:]]
        rates, bursts, now, cost = (argv[0], argv[2]), (argv[1], argv[3]), argv[4], argv[5]
        tokens, wait = [], 0.0
        for key, rate, burst in zip(keys, rates, bursts, strict=True):
            state = self.hashes.get(key, {"tokens": burst, "ts": now})
            level = min(burst, state["tokens"] + max(0.0, now - state["ts"]) * rate)
            tokens.append(level)
            if level < cost:
                wait = max(wait, (cost - level) / rate)
        allowed = 1 if wait == 0 else 0
        for i, key in enumerate(keys):
            left = tokens[i] - cost if allowed else tokens[i]
            self.hashes[key] = {"tokens": left, "ts": now}
            self.ttl[key] = int(bursts[i] / rates[i]) + 60
        return [allowed, str(wait)]


class Clock:
    now = 1_000.0

    def __call__(self) -> float:
        return self.now


RULE = BucketRule(user=RateRule(per_minute=6, burst=2), tenant=RateRule(per_minute=60, burst=3))


def _limiter(redis: Any, clock: Clock) -> ratelimit.RateLimiter:
    return ratelimit.RateLimiter(lambda: redis, clock)


def test_user_bucket_refuses_then_refills() -> None:
    redis, clock = FakeRedis(), Clock()
    limiter = _limiter(redis, clock)
    take = lambda user: asyncio.run(limiter.retry_after("tutor", RULE, TENANT, user))  # noqa: E731
    assert take(USER) is None and take(USER) is None
    wait = take(USER)
    assert wait is not None and 9.9 < wait <= 10.0  # 6/min: one token every 10 s
    clock.now += 10
    assert take(USER) is None


def test_tenant_bucket_caps_all_users_without_spending_the_user_bucket() -> None:
    redis, clock = FakeRedis(), Clock()
    limiter = _limiter(redis, clock)
    for user in (USER, USER, OTHER):
        assert asyncio.run(limiter.retry_after("tutor", RULE, TENANT, user)) is None
    assert asyncio.run(limiter.retry_after("tutor", RULE, TENANT, OTHER)) is not None
    other_key = ratelimit.bucket_keys("tutor", TENANT, OTHER)[0]
    assert redis.hashes[other_key]["tokens"] == 1  # the refused request cost nothing


def test_keys_start_with_the_tenant_and_expire() -> None:
    keys = ratelimit.bucket_keys("upload", TENANT, USER)
    assert all(k.startswith(f"{TENANT}:ratelimit:upload:") for k in keys)
    redis = FakeRedis()
    asyncio.run(_limiter(redis, Clock()).retry_after("upload", RULE, TENANT, USER))
    assert redis.ttl[keys[0]] == 80 and redis.ttl[keys[1]] == 63


def test_redis_outage_fails_open_and_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    class Down:
        async def eval(self, *_: Any) -> Any:
            raise ConnectionError("redis down")

    limiter = _limiter(Down(), Clock())
    with caplog.at_level(logging.WARNING, logger="radbrain.api"):
        for _ in range(3):
            assert asyncio.run(limiter.retry_after("tutor", RULE, TENANT, USER)) is None
    assert sum(r.getMessage() == "rate_limit_unavailable" for r in caplog.records) == 1


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    ratelimit.set_limiter(_limiter(FakeRedis(), Clock()))
    monkeypatch.setattr(get_settings(), "rate_limits", {"generate": RULE})
    memory = MemoryStudyRepo()
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.principal_context] = lambda: Principal(USER, TENANT)
    app.dependency_overrides[study.get_transport] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    ratelimit.set_limiter(None)


def test_expensive_endpoint_answers_429_with_retry_after(limited: TestClient) -> None:
    body = {"chunk_ids": [str(uuid4())], "max_cards": 3}
    statuses = [limited.post("/v1/study/cards/generate", json=body).status_code
                for _ in range(2)]
    assert 429 not in statuses
    refused = limited.post("/v1/study/cards/generate", json=body)
    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "10"
    assert ratelimit.RATE_LIMITED.value("generate") >= 1


def test_limits_can_be_switched_off(limited: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    body = {"chunk_ids": [str(uuid4())], "max_cards": 3}
    assert all(limited.post("/v1/study/cards/generate", json=body).status_code != 429
               for _ in range(5))


def test_every_expensive_route_is_limited() -> None:
    wanted = {
        ("POST", "/v1/tutor/ask"), ("POST", "/v1/tutor/ask/stream"),
        ("POST", "/v1/tutor/images"), ("POST", "/v1/questions/generate"),
        ("POST", "/v1/study/cards/generate"), ("POST", "/v1/library/sources"),
        ("POST", "/v1/viva/sessions"),
        ("POST", "/v1/viva/sessions/{session_id}/turns/{turn_no}/answer"),
        ("POST", "/v1/me/export"),
    }
    from apps.api.app.api import assessment, data_rights, library, tutor, tutor_images, viva

    found = set()
    routers = (tutor, tutor_images, assessment, study, library, viva, data_rights)
    for route in [r for module in routers for r in module.router.routes]:
        deps = getattr(route, "dependant", None)
        names = {d.call.__name__ for d in deps.dependencies} if deps else set()
        if any(n.startswith("rate_limit_") for n in names):
            found |= {(m, route.path) for m in getattr(route, "methods", ())}  # type: ignore[attr-defined]
    assert wanted <= found, sorted(wanted - found)
