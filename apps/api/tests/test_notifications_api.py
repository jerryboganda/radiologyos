"""HTTP contract for /v1/notifications with an in-memory, tenant-scoped fake session.

The fake interprets only the statements the router issues and applies them to a
store shared across sessions; each session sees only its own tenant's rows, the
way RLS scopes the real transaction. Synthetic identities only.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import notifications
from apps.api.app.security.principal import Principal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packages.notifications import push

TENANT = UUID("20000000-0000-4000-8000-000000000001")
OTHER_TENANT = UUID("20000000-0000-4000-8000-000000000002")
USER = UUID("10000000-0000-4000-8000-000000000001")
OTHER_USER = UUID("10000000-0000-4000-8000-000000000002")
ENDPOINT = "https://push.example.test/sub/one"
KEYS = {"p256dh": "p" * 20, "auth": "a" * 10}


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict[str, Any]]:
        return self.rows


@dataclass
class Store:
    subs: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[tuple[UUID, UUID], dict[str, Any]] = field(default_factory=dict)
    statements: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    commits: int = 0


class FakeSession:
    """Tenant-scoped view of ``Store`` (models the RLS the real session carries)."""

    def __init__(self, store: Store, tenant_id: UUID) -> None:
        self.store, self.tenant_id = store, tenant_id

    def _subs(self) -> list[dict[str, Any]]:
        return [s for s in self.store.subs if s["tenant_id"] == self.tenant_id]

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql, p = " ".join(str(statement).split()), dict(params or {})
        self.store.statements.append((sql, p))
        if sql.startswith("INSERT INTO push_subscriptions"):
            self._upsert_sub(p)
        elif sql.startswith("DELETE FROM push_subscriptions WHERE endpoint"):
            self.store.subs = [s for s in self.store.subs if not (
                s["tenant_id"] == self.tenant_id and s["endpoint"] == p["e"]
                and s["user_id"] == p["u"])]
        elif sql.startswith("DELETE FROM push_subscriptions WHERE id"):
            self.store.subs = [s for s in self.store.subs if s["id"] not in p["ids"]]
        elif sql.startswith("SELECT id, endpoint"):
            return _Result([s for s in self._subs() if s["user_id"] == p["u"]])
        elif sql.startswith("INSERT INTO notification_settings (tenant_id, user_id) VALUES"):
            self.store.settings.setdefault((p["t"], p["u"]), {})
        elif sql.startswith("INSERT INTO notification_settings"):
            self.store.settings[(p["t"], p["u"])] = {
                "enabled": p["enabled"], "reminder_time": p["time"], "timezone": p["tz"],
                "channels": p["channels"], "include_due_cards": p["cards"],
                "include_plan": p["plan"], "last_sent_on": None}
        elif sql.startswith("SELECT enabled"):
            row = self.store.settings.get((self.tenant_id, p["u"]))
            if row and "enabled" in row:
                cols = {k: v for k, v in row.items() if k != "last_sent_on"}
                return _Result([{**cols, "channels": json.loads(cols["channels"])}])
            return _Result([])
        else:  # pragma: no cover - a new statement must be modelled deliberately
            raise AssertionError(f"unexpected SQL: {sql[:60]}")
        return _Result([])

    def _upsert_sub(self, p: dict[str, Any]) -> None:
        assert p["t"] == self.tenant_id, "insert must carry the caller's tenant"
        existing = next((s for s in self._subs() if s["endpoint"] == p["e"]), None)
        if existing is None:
            self.store.subs.append({"id": uuid4(), "tenant_id": p["t"], "user_id": p["u"],
                                    "endpoint": p["e"], "p256dh": p["p"], "auth": p["a"],
                                    "user_agent": p["ua"], "failures": 0})
        else:
            existing.update(user_id=p["u"], p256dh=p["p"], auth=p["a"], failures=0)

    async def commit(self) -> None:
        self.store.commits += 1


class Caller:
    principal = Principal(USER, TENANT)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(notifications.router)
    return app


APP = _app()


@pytest.fixture
def store() -> Iterator[Store]:
    memory = Store()
    Caller.principal = Principal(USER, TENANT)
    APP.dependency_overrides[notifications.principal_context] = lambda: Caller.principal
    APP.dependency_overrides[notifications.tenant_db_session] = (
        lambda: FakeSession(memory, Caller.principal.tenant_id))
    yield memory
    APP.dependency_overrides.clear()


@pytest.fixture
def client(store: Store) -> TestClient:
    return TestClient(APP)


def _as(user: UUID, tenant: UUID = TENANT) -> None:
    Caller.principal = Principal(user, tenant)


def _subscribe(client: TestClient, endpoint: str = ENDPOINT, **overrides: Any) -> Any:
    return client.post("/v1/notifications/subscriptions",
                       json={"endpoint": endpoint, **KEYS, **overrides})


def test_every_route_requires_credentials() -> None:
    anonymous = TestClient(_app())
    body = {"endpoint": ENDPOINT, **KEYS}
    assert anonymous.get("/v1/notifications/vapid-public-key").status_code == 401
    assert anonymous.post("/v1/notifications/subscriptions", json=body).status_code == 401
    assert anonymous.request("DELETE", "/v1/notifications/subscriptions",
                             json={"endpoint": ENDPOINT}).status_code == 401
    assert anonymous.get("/v1/notifications/settings").status_code == 401
    assert anonymous.put("/v1/notifications/settings", json={}).status_code == 401
    assert anonymous.post("/v1/notifications/test").status_code == 401


def test_vapid_key_is_enabled_only_with_both_halves(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    url = "/v1/notifications/vapid-public-key"
    assert client.get(url).json() == {"public_key": None, "enabled": False}
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "synthetic-public")
    assert client.get(url).json() == {"public_key": "synthetic-public", "enabled": False}
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "synthetic-private-secret")
    response = client.get(url)
    assert response.json() == {"public_key": "synthetic-public", "enabled": True}
    assert "synthetic-private-secret" not in response.text


def test_subscribe_upserts_per_endpoint_and_seeds_settings(
    client: TestClient, store: Store
) -> None:
    assert _subscribe(client, user_agent="SyntheticBrowser/1").status_code == 204
    assert len(store.subs) == 1 and store.subs[0]["user_id"] == USER
    assert store.subs[0]["tenant_id"] == TENANT
    assert (TENANT, USER) in store.settings and store.commits == 1
    store.subs[0]["failures"] = 3
    renewed = _subscribe(client, p256dh="q" * 20, auth="b" * 10)
    assert renewed.status_code == 204
    assert len(store.subs) == 1
    assert store.subs[0]["p256dh"] == "q" * 20 and store.subs[0]["auth"] == "b" * 10
    assert store.subs[0]["failures"] == 0


def test_subscribe_never_overwrites_saved_settings(client: TestClient) -> None:
    saved = {"enabled": False, "reminder_time": "07:30:00", "timezone": "Europe/London",
             "channels": ["push", "email"], "include_due_cards": False, "include_plan": True}
    assert client.put("/v1/notifications/settings", json=saved).status_code == 200
    assert _subscribe(client).status_code == 204
    assert client.get("/v1/notifications/settings").json() == saved


@pytest.mark.parametrize("overrides", [
    {"endpoint": "http://push.example.test/sub"},
    {"endpoint": "push.example.test/sub"},
    {"endpoint": "https://push.example.test/" + "x" * 2030},
    {"p256dh": "p" * 15},
    {"p256dh": "p" * 256},
    {"auth": "a" * 7},
    {"user_agent": "u" * 301},
    {"unexpected": "field"},
])
def test_subscription_body_is_validated(
    client: TestClient, store: Store, overrides: dict[str, Any]
) -> None:
    body = {"endpoint": ENDPOINT, **KEYS, **overrides}
    assert client.post("/v1/notifications/subscriptions", json=body).status_code == 422
    assert store.subs == [] and store.commits == 0


def test_subscription_body_requires_all_keys(client: TestClient) -> None:
    for missing in ("endpoint", "p256dh", "auth"):
        body = {k: v for k, v in {"endpoint": ENDPOINT, **KEYS}.items() if k != missing}
        assert client.post("/v1/notifications/subscriptions", json=body).status_code == 422


def test_unsubscribe_removes_only_the_callers_subscription(
    client: TestClient, store: Store
) -> None:
    _subscribe(client)
    _as(OTHER_USER)
    gone = client.request("DELETE", "/v1/notifications/subscriptions",
                          json={"endpoint": ENDPOINT})
    assert gone.status_code == 204
    assert [s["user_id"] for s in store.subs] == [USER]
    delete_sql, params = store.statements[-1]
    assert delete_sql.startswith("DELETE") and params["u"] == OTHER_USER
    _as(USER)
    client.request("DELETE", "/v1/notifications/subscriptions", json={"endpoint": ENDPOINT})
    assert store.subs == []


def test_unsubscribe_body_is_validated(client: TestClient) -> None:
    url = "/v1/notifications/subscriptions"
    assert client.request("DELETE", url, json={}).status_code == 422
    assert client.request("DELETE", url, json={"endpoint": ENDPOINT, "x": 1}).status_code == 422
    too_long = {"endpoint": "https://p.test/" + "x" * 2040}
    assert client.request("DELETE", url, json=too_long).status_code == 422


def test_settings_default_then_round_trip_per_user(client: TestClient, store: Store) -> None:
    defaults = client.get("/v1/notifications/settings").json()
    assert defaults == {"enabled": True, "reminder_time": "19:00:00",
                        "timezone": "Asia/Karachi", "channels": ["push"],
                        "include_due_cards": True, "include_plan": True}
    body = {**defaults, "reminder_time": "06:15:00", "include_plan": False}
    saved = client.put("/v1/notifications/settings", json=body)
    assert saved.status_code == 200 and saved.json() == body
    assert client.get("/v1/notifications/settings").json() == body
    assert store.settings[(TENANT, USER)]["last_sent_on"] is None
    _as(OTHER_USER)
    assert client.get("/v1/notifications/settings").json() == defaults


def test_other_tenant_cannot_see_settings_or_subscriptions(
    client: TestClient, store: Store
) -> None:
    client.put("/v1/notifications/settings", json={"enabled": False})
    _subscribe(client)
    _as(USER, OTHER_TENANT)
    assert client.get("/v1/notifications/settings").json()["enabled"] is True
    client.request("DELETE", "/v1/notifications/subscriptions", json={"endpoint": ENDPOINT})
    assert len(store.subs) == 1


@pytest.mark.parametrize("overrides", [
    {"timezone": "Mars/Olympus"},
    {"channels": ["sms"]},
    {"reminder_time": "25:00"},
    {"enabled": "sometimes"},
    {"unexpected": True},
])
def test_settings_body_is_validated(
    client: TestClient, store: Store, overrides: dict[str, Any]
) -> None:
    assert client.put("/v1/notifications/settings", json=overrides).status_code == 422
    assert store.settings == {} and store.commits == 0


def test_test_push_is_unavailable_without_private_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert client.post("/v1/notifications/test").status_code == 503


def test_test_push_with_no_subscriptions_sends_nothing(
    client: TestClient, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "synthetic-private")
    response = client.post("/v1/notifications/test")
    assert response.status_code == 202 and response.json() == {"sent": 0, "removed": 0}
    assert store.commits == 0


def test_test_push_targets_caller_and_prunes_gone_endpoints(
    client: TestClient, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "synthetic-private")
    for name in ("ok", "gone", "flaky"):
        _subscribe(client, endpoint=f"https://push.example.test/{name}")
    _as(OTHER_USER)
    _subscribe(client, endpoint="https://push.example.test/someone-else")
    _as(USER)
    sent: list[tuple[str, dict[str, Any], str]] = []

    def fake_send(sub: push.Subscription, payload: dict[str, Any], private: str) -> None:
        sent.append((sub.endpoint, payload, private))
        if sub.endpoint.endswith("gone"):
            raise push.PushGone("410")
        if sub.endpoint.endswith("flaky"):
            raise push.PushFailed("500")

    monkeypatch.setattr(push, "send", fake_send)
    response = client.post("/v1/notifications/test")
    assert response.status_code == 202 and response.json() == {"sent": 1, "removed": 1}
    assert sorted(e.rsplit("/", 1)[1] for e, _, _ in sent) == ["flaky", "gone", "ok"]
    assert all(private == "synthetic-private" for _, _, private in sent)
    assert all(set(payload) == {"title", "body", "url"} for _, payload, _ in sent)
    remaining = sorted(s["endpoint"].rsplit("/", 1)[1] for s in store.subs)
    assert remaining == ["flaky", "ok", "someone-else"]
