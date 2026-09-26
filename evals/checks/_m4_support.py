"""Shared wiring for the M4 planner gate: durable study routers over in-memory repos.

The gate mounts only the durable ``/v1/study`` routers on a private FastAPI app
(so it never depends on the full application's router list) and overrides the
three seams the routers expose: the principal, the repository, and the clock.
Each tenant gets its own ``MemorySessionRepo``, standing in for the tenant's
RLS-scoped database session; inside a tenant the repo scopes every read to the
calling user, exactly as ``SqlStudyRepo`` does. The row-level-security proof
itself runs against PostgreSQL in ``evals/checks/test_study_live.py`` and
``test_study_sessions_live.py``.

All content is synthetic.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.api import study, study_sessions
from apps.api.app.security.principal import Principal
from apps.api.tests.session_fakes import MemorySessionRepo
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

# 2026-09-28 is a Monday, so the weekday budget (``daily_minutes``) applies.
NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
TODAY = NOW.date()
TENANT_A = UUID("20000000-0000-4000-8000-0000000000a4")
TENANT_B = UUID("20000000-0000-4000-8000-0000000000b4")
OWNER_A = UUID("10000000-0000-4000-8000-0000000000a4")
OWNER_B = UUID("10000000-0000-4000-8000-0000000000b4")
BANDS = {"weak", "learning", "mastered"}


class Who:
    """The mutable caller and clock the overridden dependencies read."""

    user = OWNER_A
    tenant = TENANT_A
    now = NOW

    @classmethod
    def reset(cls) -> None:
        cls.user, cls.tenant, cls.now = OWNER_A, TENANT_A, NOW

    @classmethod
    def act_as(cls, user: UUID, tenant: UUID) -> None:
        cls.user, cls.tenant = user, tenant


class Harness:
    """A test client over the durable study routers with one repo per tenant."""

    def __init__(self) -> None:
        Who.reset()
        self.repos: defaultdict[UUID, MemorySessionRepo] = defaultdict(MemorySessionRepo)
        app = FastAPI()
        app.include_router(study.router)
        app.include_router(study_sessions.router)

        def principal() -> Principal:
            return Principal(Who.user, Who.tenant)

        def repo_for(caller: Annotated[Principal, Depends(study.principal_context)]) -> Any:
            return self.repos[caller.tenant_id]

        app.dependency_overrides[study.principal_context] = principal
        app.dependency_overrides[study.get_repo] = repo_for
        app.dependency_overrides[study.get_now] = lambda: Who.now
        self.client = TestClient(app)

    @property
    def repo(self) -> MemorySessionRepo:
        """Tenant A's repository (the default caller's tenant)."""
        return self.repos[TENANT_A]

    def put_profile(self, days: int = 365, minutes: int = 60, **extra: Any) -> Any:
        exam: date = Who.now.date() + timedelta(days=days)
        body = {"exam_date": exam.isoformat(), "exam_targets": ["fcps2_theory"],
                "daily_minutes": minutes, "timezone": "UTC", **extra}
        return self.client.put("/v1/study/profile", json=body)

    def onboard(self, days: int = 365, minutes: int = 60) -> dict[str, Any]:
        response = self.put_profile(days, minutes)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def today(self, refresh: bool = False) -> dict[str, Any]:
        response = self.client.get("/v1/study/today", params={"refresh": refresh})
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def progress(self) -> dict[str, Any]:
        response = self.client.get("/v1/study/progress")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def add_card(self, code: str = "CHEST", front: str = "Classic HRCT sign of PAP?",
                 owner: UUID | None = None) -> dict[str, Any]:
        chunk = self.repos[Who.tenant].add_chunk(owner or Who.user)
        response = self.client.post("/v1/study/cards", json={
            "chunk_id": str(chunk), "curriculum_code": code, "topic": "synthetic topic",
            "front": front, "back": "Crazy paving."})
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    def review(self, card_id: str, rating: int) -> Any:
        return self.client.post(f"/v1/study/cards/{card_id}/review", json={"rating": rating})

    def due(self, limit: int = 50) -> list[dict[str, Any]]:
        response = self.client.get("/v1/study/cards/due", params={"limit": limit})
        assert response.status_code == 200, response.text
        body: list[dict[str, Any]] = response.json()
        return body

    def approve_weights(self, owner: UUID, weights: dict[str, float]) -> None:
        for code, weight in weights.items():
            self.repos[Who.tenant].weights.append((owner, {
                "exam_target": "fcps2_theory", "curriculum_code": code, "weight": weight}))


def probability_keys(value: Any) -> list[str]:
    """Every JSON key anywhere in ``value`` that mentions a probability."""
    if isinstance(value, dict):
        own = [key for key in value if "probab" in key.lower()]
        return own + [key for item in value.values() for key in probability_keys(item)]
    if isinstance(value, list):
        return [key for item in value for key in probability_keys(item)]
    return []


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
