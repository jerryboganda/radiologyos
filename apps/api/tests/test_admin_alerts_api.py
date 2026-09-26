"""Admin embedding-usage view and alert acknowledgement over a small fake session."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import admin_usage
from apps.api.app.security.principal import Principal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packages.models import gateway

TENANT = UUID("40000000-0000-4000-8000-000000000001")
ADMIN = UUID("10000000-0000-4000-8000-00000000000a")
SECOND_ADMIN = UUID("10000000-0000-4000-8000-00000000000b")
T0 = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)


class _Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def mappings(self) -> list[dict[str, Any]]:
        return self.value


@dataclass
class FakeSession:
    alerts: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    tokens: int = 0
    sql: list[str] = field(default_factory=list)
    commits: int = 0
    clock: datetime = T0

    def add(self, level: str, age_days: int, acked: bool = False) -> UUID:
        alert_id = uuid4()
        self.alerts[alert_id] = {
            "id": alert_id, "level": level, "created_at": T0 - timedelta(days=age_days),
            "acknowledged_at": T0 if acked else None, "acknowledged_by": ADMIN if acked else None}
        return alert_id

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql, p = " ".join(str(statement).split()), params or {}
        self.sql.append(sql)
        if "embedding_tokens_total" in sql:
            return _Result(self.tokens)
        if sql.startswith("UPDATE ops_alerts"):
            alert = self.alerts.get(p["id"])
            if alert is None or alert["acknowledged_at"] is not None:
                return _Result(None)
            self.clock += timedelta(minutes=1)
            alert.update(acknowledged_at=self.clock, acknowledged_by=p["u"])
            return _Result(p["id"])
        if sql.startswith("SELECT 1 FROM ops_alerts"):
            return _Result(1 if p["id"] in self.alerts else None)
        if sql.startswith("SELECT id, level"):
            rows = sorted(self.alerts.values(), key=lambda a: a["created_at"], reverse=True)
            return _Result([{k: a[k] for k in ("id", "level", "created_at", "acknowledged_at")}
                            for a in rows])
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    async def commit(self) -> None:
        self.commits += 1


class Caller:
    role = "org_admin"
    user = ADMIN


APP = FastAPI()
APP.include_router(admin_usage.router)


@pytest.fixture
def session() -> Iterator[FakeSession]:
    fake = FakeSession()
    Caller.role, Caller.user = "org_admin", ADMIN
    APP.dependency_overrides[admin_usage.principal_context] = (
        lambda: Principal(Caller.user, TENANT, Caller.role))
    APP.dependency_overrides[admin_usage.tenant_db_session] = lambda: fake
    yield fake
    APP.dependency_overrides.clear()


@pytest.fixture
def client(session: FakeSession) -> TestClient:
    return TestClient(APP)


def _ack(client: TestClient, alert_id: UUID | str) -> Any:
    return client.post(f"/v1/admin/alerts/{alert_id}/ack")


def test_routes_require_credentials() -> None:
    anonymous = TestClient(APP)
    assert _ack(anonymous, uuid4()).status_code == 401
    assert anonymous.get("/v1/admin/embedding-usage").status_code == 401


@pytest.mark.parametrize("role", ["student", "editor"])
def test_non_admin_roles_are_refused_before_any_query(
    client: TestClient, session: FakeSession, role: str
) -> None:
    alert_id = session.add("red", 1)
    Caller.role = role
    assert _ack(client, alert_id).status_code == 403
    assert client.get("/v1/admin/embedding-usage").status_code == 403
    assert session.sql == [] and session.commits == 0
    assert session.alerts[alert_id]["acknowledged_at"] is None


@pytest.mark.parametrize("role", ["org_admin", "superadmin"])
def test_admin_acknowledges_an_open_alert_as_the_caller(
    client: TestClient, session: FakeSession, role: str
) -> None:
    alert_id = session.add("amber", 2)
    Caller.role = role
    response = _ack(client, alert_id)
    assert response.status_code == 204 and response.content == b""
    alert = session.alerts[alert_id]
    assert alert["acknowledged_at"] is not None and alert["acknowledged_by"] == ADMIN
    assert session.commits == 1


def test_unknown_alert_is_404_and_nothing_is_committed(
    client: TestClient, session: FakeSession
) -> None:
    session.add("red", 1)
    assert _ack(client, uuid4()).status_code == 404
    assert session.commits == 0


def test_malformed_alert_id_is_rejected(client: TestClient, session: FakeSession) -> None:
    assert _ack(client, "not-a-uuid").status_code == 422
    assert session.sql == []


def test_second_ack_is_idempotent_and_keeps_the_first_acknowledger(
    client: TestClient, session: FakeSession
) -> None:
    alert_id = session.add("red", 1)
    assert _ack(client, alert_id).status_code == 204
    first = dict(session.alerts[alert_id])
    Caller.user = SECOND_ADMIN
    assert _ack(client, alert_id).status_code == 204
    assert session.alerts[alert_id] == first
    assert session.alerts[alert_id]["acknowledged_by"] == ADMIN


def test_usage_lists_alerts_newest_first_with_ack_state(
    client: TestClient, session: FakeSession
) -> None:
    old = session.add("amber", 5, acked=True)
    new = session.add("red", 1)
    session.tokens = gateway.routing_config().embeddings.budget.hard_cap_tokens
    body = client.get("/v1/admin/embedding-usage").json()
    assert body["status"] == "red" and body["tokens_used"] == session.tokens
    assert [a["id"] for a in body["alerts"]] == [str(new), str(old)]
    assert body["alerts"][0]["acknowledged_at"] is None
    assert body["alerts"][1]["acknowledged_at"] is not None
    assert "acknowledged_by" not in body["alerts"][1]


def test_usage_reports_amber_at_the_warning_threshold(
    client: TestClient, session: FakeSession
) -> None:
    budget = gateway.routing_config().embeddings.budget
    session.tokens = budget.warn_tokens
    body = client.get("/v1/admin/embedding-usage").json()
    assert body["status"] == "amber" and body["alerts"] == []
    assert body["hard_cap_tokens"] == budget.hard_cap_tokens
    assert body["free_tier_remaining"] >= 0


def test_usage_is_404_when_embeddings_are_not_configured(
    client: TestClient, session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gateway, "routing_config", lambda: SimpleNamespace(embeddings=None))
    assert client.get("/v1/admin/embedding-usage").status_code == 404
    assert session.sql == []
