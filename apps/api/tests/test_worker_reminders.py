"""Daily push reminders (apps/worker/app/reminders.py) with a fake engine and session.

Every tenant read/write must run inside ``tenant_tx(engine, tenant_id)``; the
cross-tenant resolver returns ids only. Payloads carry counts, never content.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.worker.app import reminders
from packages.notifications import push

TENANT = UUID("20000000-0000-4000-8000-000000000001")
OTHER_TENANT = UUID("20000000-0000-4000-8000-000000000002")
USER = UUID("10000000-0000-4000-8000-000000000001")
OTHER_USER = UUID("10000000-0000-4000-8000-000000000002")


class _Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> _Result:
        return self

    def all(self) -> Any:
        return self.value

    def one(self) -> Any:
        return self.value

    def first(self) -> Any:
        return self.value

    def scalar_one(self) -> Any:
        return self.value


class World:
    """Scripted database state plus a log of (tenant scope, sql, params)."""

    def __init__(self) -> None:
        self.subs: dict[UUID, list[dict[str, Any]]] = {}
        self.tables = (True, True)
        self.due_cards = 4
        self.profile: tuple[Any, Any] | None = None
        self.due: list[tuple[Any, Any]] = []
        self.log: list[tuple[UUID | None, str, dict[str, Any]]] = []


class FakeSession:
    def __init__(self, world: World, tenant: UUID | None) -> None:
        self.world, self.tenant = world, tenant

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql, p, w = " ".join(str(statement).split()), dict(params or {}), self.world
        w.log.append((self.tenant, sql, p))
        if "app.due_reminders" in sql:
            return _Result(w.due)
        if sql.startswith("SELECT id, endpoint"):
            return _Result(w.subs.get(p["u"], []))
        if "to_regclass" in sql:
            return _Result(w.tables)
        if sql.startswith("SELECT count(*) FROM cards"):
            return _Result(w.due_cards)
        if sql.startswith("SELECT exam_date"):
            return _Result(w.profile)
        return _Result(None)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    state = World()

    @asynccontextmanager
    async def fake_tenant_tx(engine: Any, tenant_id: UUID) -> AsyncIterator[FakeSession]:
        assert engine == "engine"
        yield FakeSession(state, tenant_id)

    monkeypatch.setattr(reminders, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(reminders, "AsyncSession", lambda engine: FakeSession(state, None))
    return state


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any], str]]:
    calls: list[tuple[str, dict[str, Any], str]] = []

    def fake_send(sub: push.Subscription, payload: dict[str, Any], private: str) -> None:
        calls.append((sub.endpoint, payload, private))
        if sub.endpoint.endswith("/gone"):
            raise push.PushGone("410")
        if sub.endpoint.endswith("/flaky"):
            raise push.PushFailed("503")

    monkeypatch.setattr(push, "send", fake_send)
    return calls


def _sub(name: str) -> dict[str, Any]:
    return {"id": uuid4(), "endpoint": f"https://push.example.test/{name}",
            "p256dh": "p" * 20, "auth": "a" * 10}


def test_task_is_a_no_op_without_a_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(reminders, "make_engine", lambda: pytest.fail("engine opened"))
    assert reminders.send_due_reminders.run() == 0


@pytest.mark.parametrize("fails", [False, True])
def test_task_always_disposes_its_engine(monkeypatch: pytest.MonkeyPatch, fails: bool) -> None:
    disposed: list[bool] = []

    class Engine:
        async def dispose(self) -> None:
            disposed.append(True)

    async def fake_send_all(engine: Any, private: str) -> int:
        assert private == "synthetic-private"
        if fails:
            raise RuntimeError("db down")
        return 3

    monkeypatch.setenv("VAPID_PRIVATE_KEY", "synthetic-private")
    monkeypatch.setattr(reminders, "make_engine", Engine)
    monkeypatch.setattr(reminders, "_send_all", fake_send_all)
    if fails:
        with pytest.raises(RuntimeError):
            reminders.send_due_reminders.run()
    else:
        assert reminders.send_due_reminders.run() == 3
    assert disposed == [True]


async def test_send_all_fans_out_per_due_user_with_uuid_ids(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.due = [(str(TENANT), str(USER)), (OTHER_TENANT, OTHER_USER)]
    calls: list[tuple[UUID, UUID, str]] = []

    async def fake_remind(engine: Any, tenant: UUID, user: UUID, private: str) -> int:
        calls.append((tenant, user, private))
        return 2

    monkeypatch.setattr(reminders, "_remind", fake_remind)
    assert await reminders._send_all("engine", "k") == 4  # type: ignore[arg-type]
    assert calls == [(TENANT, USER, "k"), (OTHER_TENANT, OTHER_USER, "k")]
    resolver = [entry for entry in world.log if "due_reminders" in entry[1]]
    assert len(resolver) == 1 and resolver[0][0] is None
    assert "now" in resolver[0][2]


async def test_send_all_with_nobody_due_sends_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reminders, "_remind", lambda *a: pytest.fail("no user is due"))
    assert await reminders._send_all("engine", "k") == 0  # type: ignore[arg-type]


async def test_remind_pushes_counts_and_prunes_gone_subscriptions(
    world: World, sent: list[tuple[str, dict[str, Any], str]]
) -> None:
    subs = [_sub("ok"), _sub("gone"), _sub("flaky")]
    world.subs[USER] = subs
    world.profile = (datetime.now(UTC).date() + timedelta(days=30), 90)
    assert await reminders._remind("engine", TENANT, USER, "k") == 1  # type: ignore[arg-type]
    assert [e.rsplit("/", 1)[1] for e, _, _ in sent] == ["ok", "gone", "flaky"]
    payload = sent[0][1]
    assert payload == push.reminder_payload(4, 30, 90)
    assert all(p == "k" for _, _, p in sent)
    deletes = [p for _, sql, p in world.log if sql.startswith("DELETE FROM push_subscriptions")]
    assert deletes == [{"ids": [subs[1]["id"]]}]


async def test_every_statement_runs_in_the_users_tenant_and_is_user_scoped(
    world: World, sent: list[tuple[str, dict[str, Any], str]]
) -> None:
    world.subs[USER] = [_sub("gone")]
    await reminders._remind("engine", TENANT, USER, "k")  # type: ignore[arg-type]
    assert world.log and all(tenant == TENANT for tenant, _, _ in world.log)
    user_scoped = [p for _, sql, p in world.log if "WHERE user_id" in sql]
    assert len(user_scoped) == 4 and all(p["u"] == USER for p in user_scoped)
    stamped = [sql for _, sql, _ in world.log if sql.startswith("UPDATE notification_settings")]
    assert len(stamped) == 1 and "last_sent_on" in stamped[0]


async def test_reminder_day_is_stamped_even_without_subscriptions(
    world: World, sent: list[tuple[str, dict[str, Any], str]]
) -> None:
    assert await reminders._remind("engine", TENANT, USER, "k") == 0  # type: ignore[arg-type]
    assert sent == []
    assert any(sql.startswith("UPDATE notification_settings") for _, sql, _ in world.log)
    assert not any(sql.startswith("DELETE") for _, sql, _ in world.log)


async def test_facts_are_null_when_study_tables_are_absent(world: World) -> None:
    world.tables = (False, False)
    session: Any = FakeSession(world, TENANT)
    facts = await reminders._facts(session, USER)
    assert facts == {"due_cards": None, "days_to_exam": None, "plan_minutes": None}
    assert len(world.log) == 1


@pytest.mark.parametrize(("profile", "days", "minutes"), [
    (None, None, None),
    ((None, 45), None, 45),
    ("past", 0, 60),
])
async def test_facts_handle_missing_profile_exam_date_and_past_exams(
    world: World, profile: Any, days: int | None, minutes: int | None
) -> None:
    if profile == "past":
        profile = (datetime.now(UTC).date() - timedelta(days=3), 60)
    world.profile = profile
    session: Any = FakeSession(world, TENANT)
    facts = await reminders._facts(session, USER)
    assert facts == {"due_cards": 4, "days_to_exam": days, "plan_minutes": minutes}


def test_task_is_registered_under_its_beat_name() -> None:
    assert reminders.send_due_reminders.name == "radbrain.send_due_reminders"
