"""Study beat tasks (apps/worker/app/study_jobs.py) with a fake engine and session.

A narrow resolver names due users; each user's job then runs in its own
session whose first statement pins ``app.tenant_id`` to that user's tenant.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from apps.worker.app import study_jobs

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
T1 = UUID("20000000-0000-4000-8000-000000000001")
T2 = UUID("20000000-0000-4000-8000-000000000002")
U1 = UUID("10000000-0000-4000-8000-000000000001")
U2 = UUID("10000000-0000-4000-8000-000000000002")
U3 = UUID("10000000-0000-4000-8000-000000000003")
DUE_SQL = "SELECT tenant_id, user_id FROM app.weekly_reports_due(:now)"


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    """Each instance is one session; ``opened`` records every session's statements."""

    due: list[tuple[Any, Any]] = []
    opened: list[FakeSession] = []

    def __init__(self, engine: Any, **kwargs: Any) -> None:
        self.engine, self.kwargs = engine, kwargs
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        FakeSession.opened.append(self)

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.closed = True

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = " ".join(str(statement).split())
        self.statements.append((sql, dict(params or {})))
        return _Result(FakeSession.due if "_due(" in sql else [])


@pytest.fixture(autouse=True)
def fake_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSession.due, FakeSession.opened = [], []
    monkeypatch.setattr(study_jobs, "AsyncSession", FakeSession)


async def test_job_runs_once_per_due_user_in_that_users_tenant() -> None:
    FakeSession.due = [(str(T1), str(U1)), (T2, U2)]
    seen: list[tuple[UUID, UUID, datetime, FakeSession]] = []

    async def job(repo: Any, user_id: UUID, now: datetime) -> None:
        seen.append((repo.tenant_id, user_id, now, repo.session))
        await repo.session.execute("SELECT 1 FROM study_profiles")

    done = await study_jobs.run_for_due("engine", DUE_SQL, {"now": NOW}, job, NOW)  # type: ignore[arg-type]
    assert done == 2
    assert [(t, u, n) for t, u, n, _ in seen] == [(T1, U1, NOW), (T2, U2, NOW)]
    resolver, *per_user = FakeSession.opened
    assert resolver.statements == [(DUE_SQL, {"now": NOW})]
    assert [s for _, _, _, s in seen] == per_user
    for session, tenant in zip(per_user, (T1, T2), strict=True):
        first_sql, first_params = session.statements[0]
        assert "set_config('app.tenant_id'" in first_sql and "true" in first_sql
        assert first_params == {"t": str(tenant)}
        assert session.kwargs == {"expire_on_commit": False} and session.closed


async def test_each_user_gets_a_fresh_session() -> None:
    FakeSession.due = [(T1, U1), (T1, U3)]
    sessions: list[Any] = []

    async def job(repo: Any, user_id: UUID, now: datetime) -> None:
        sessions.append(repo.session)

    await study_jobs.run_for_due("engine", DUE_SQL, {}, job, NOW)  # type: ignore[arg-type]
    assert len({id(s) for s in sessions}) == 2


async def test_one_users_failure_does_not_block_others_and_logs_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    FakeSession.due = [(T1, U1), (T1, U2), (T2, U3)]
    ran: list[UUID] = []

    async def job(repo: Any, user_id: UUID, now: datetime) -> None:
        ran.append(user_id)
        if user_id == U2:
            raise LookupError("synthetic private detail about user")

    with caplog.at_level(logging.WARNING, logger="radbrain.study_jobs"):
        done = await study_jobs.run_for_due("engine", DUE_SQL, {}, job, NOW)  # type: ignore[arg-type]
    assert done == 2 and ran == [U1, U2, U3]
    assert "kind=LookupError" in caplog.text
    assert "private detail" not in caplog.text and str(U2) not in caplog.text


async def test_nobody_due_runs_nothing() -> None:
    async def job(repo: Any, user_id: UUID, now: datetime) -> None:
        pytest.fail("no user is due")

    assert await study_jobs.run_for_due("engine", DUE_SQL, {}, job, NOW) == 0  # type: ignore[arg-type]
    assert len(FakeSession.opened) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_run_disposes_its_engine(monkeypatch: pytest.MonkeyPatch, fails: bool) -> None:
    disposed: list[bool] = []

    class Engine:
        async def dispose(self) -> None:
            disposed.append(True)

    async def fake_run_for_due(engine: Any, sql: str, params: Any, job: Any, now: Any) -> int:
        assert isinstance(engine, Engine)
        if fails:
            raise RuntimeError("resolver failed")
        return 5

    monkeypatch.setattr(study_jobs, "make_engine", Engine)
    monkeypatch.setattr(study_jobs, "run_for_due", fake_run_for_due)
    if fails:
        with pytest.raises(RuntimeError):
            study_jobs._run(DUE_SQL, {}, lambda *a: None, NOW)  # type: ignore[arg-type,return-value]
    else:
        assert study_jobs._run(DUE_SQL, {}, lambda *a: None, NOW) == 5  # type: ignore[arg-type,return-value]
    assert disposed == [True]


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any], Any]]:
    calls: list[tuple[str, dict[str, Any], Any]] = []

    def fake_run(sql: str, params: dict[str, Any], job: Any, now: datetime) -> int:
        calls.append((sql, params, job))
        assert params["now"] == now and now.tzinfo is UTC
        return 1

    monkeypatch.setattr(study_jobs, "_run", fake_run)
    return calls


def test_weekly_reports_uses_the_ids_only_resolver_and_report_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.app.study.reports import store_weekly_report

    calls = _capture(monkeypatch)
    assert study_jobs.weekly_reports.run() == 1
    (sql, params, job), = calls
    assert sql == DUE_SQL and set(params) == {"now"} and job is store_weekly_report


def test_nightly_replan_is_keyed_on_the_planner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app.study.service import plan_for_tomorrow
    from packages.study.planner import PLANNER_VERSION

    calls = _capture(monkeypatch)
    assert study_jobs.nightly_replan.run() == 1
    (sql, params, job), = calls
    assert sql == "SELECT tenant_id, user_id FROM app.study_replans_due(:now, :v)"
    assert params["v"] == PLANNER_VERSION and job is plan_for_tomorrow


def test_tasks_are_registered_under_their_beat_names() -> None:
    assert study_jobs.weekly_reports.name == "radbrain.weekly_reports"
    assert study_jobs.nightly_replan.name == "radbrain.nightly_replan"
