"""Opt-in live proof for migration 0016 (Today sessions, weakness loop) as the runtime role.

* study_sessions, study_session_steps and weakness_events hide tenant A's rows from
  tenant B, reject writes carrying a foreign tenant_id, and show nothing without a
  tenant context;
* the real services build one session per user and local day (a second build
  returns the same row), record a wrong SBA answer with its confidence, create a
  weakness card due within two days plus a re-test event exactly once per attempt,
  feed a wrong exam answer into the same loop, freeze a completion summary, and
  compute insights, while tenant B sees none of it.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from packages.library import storage  # noqa: E402

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
QUESTIONS = 6
TABLES = ("study_sessions", "study_session_steps", "weakness_events")
CLEANUP = ("weakness_events", "study_session_steps", "study_sessions", "card_reviews", "cards",
           "attempts", "grading_jobs", "exams", "questions", "curriculum_mappings",
           "topic_weights", "study_plans", "study_profiles", "chunks", "audit_log", "sources")


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("study sessions live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run this proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


def _option(text: str) -> dict[str, Any]:
    return {"text": text, "explanation": "Because.", "citations": []}


async def _seed_people(admin: Any, ids: dict[str, Any]) -> None:
    await admin.execute("INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Loop A'),"
                        "($2,'personal','Loop B')", ids["ta"], ids["tb"])
    for user, tenant in (("ua", "ta"), ("ub", "tb")):
        await admin.execute(
            "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
            ids[user], ids[tenant], f"loop-{ids[user]}", f"{ids[user]}@example.invalid")
    exam_date = datetime.now(UTC).date() + timedelta(days=100)
    for user, tenant in (("ua", "ta"), ("ub", "tb")):
        await admin.execute(
            "INSERT INTO study_profiles (tenant_id, user_id, exam_date, exam_targets, timezone) "
            "VALUES ($1,$2,$3,ARRAY['fcps2_theory'],'UTC')", ids[tenant], ids[user], exam_date)


async def _seed_library(admin: Any, ids: dict[str, Any]) -> None:
    await admin.execute(
        "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
        "title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic loop')",
        ids["sa"], ids["ta"], ids["ua"], uuid4().hex + uuid4().hex,
        storage.original_key(ids["ta"], ids["sa"], "pdf"))
    await admin.execute(
        "INSERT INTO chunks (id, tenant_id, source_id, chunk_no, page_from, page_to, heading, "
        "text, block_refs) VALUES ($1,$2,$3,0,1,1,'PAP','Crazy paving on HRCT.','[]')",
        ids["ca"], ids["ta"], ids["sa"])
    await admin.execute(
        "INSERT INTO curriculum_mappings (tenant_id, source_id, unit_hash, chunk_id, page_from, "
        "page_to, curriculum_code, confidence, status, agent_version) "
        "VALUES ($1,$2,'0123456789abcdef',$3,1,1,'CHEST',0.9,'accepted','v1')",
        ids["ta"], ids["sa"], ids["ca"])
    await admin.execute(
        "INSERT INTO topic_weights (tenant_id, user_id, exam_target, curriculum_code, weight, "
        "basis, approved, approved_by, approved_at) VALUES "
        "($1,$2,'fcps2_theory','CHEST',0.9,'{}'::jsonb,true,$2,now()),"
        "($1,$2,'fcps2_theory','NEURO',0.1,'{}'::jsonb,true,$2,now())", ids["ta"], ids["ua"])
    citation = json.dumps([{"ref": "E1", "kind": "chunk", "chunk_id": str(ids["ca"])}])
    options = json.dumps([_option(t) for t in "ABCDE"])
    for qid in ids["questions"]:
        await admin.execute(
            "INSERT INTO questions (id, tenant_id, user_id, type, topic, stem, options, answer, "
            "explanation, citations, status, agent_version) VALUES ($1,$2,$3,'sba','PAP',"
            "'Synthetic stem?',$4::jsonb,'{\"key\": 0}'::jsonb,'Crazy paving.',$5::jsonb,"
            "'active','v1')", qid, ids["ta"], ids["ua"], options, citation)


async def _seed(admin: Any) -> dict[str, Any]:
    ids: dict[str, Any] = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "ca")}
    ids["questions"] = [uuid4() for _ in range(QUESTIONS)]
    async with admin.transaction():
        await _seed_people(admin, ids)
        await _seed_library(admin, ids)
    return ids


async def _cleanup(admin: Any, ids: dict[str, Any]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in CLEANUP:
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


def _inserts(ids: dict[str, Any]) -> dict[str, tuple[str, tuple[Any, ...]]]:
    ta, ua, sid = ids["ta"], ids["ua"], ids["session"]
    return {
        "study_sessions": ("INSERT INTO study_sessions (id, tenant_id, user_id, session_date, "
                           "session_version, plan_version) VALUES ($1,$2,$3,'2026-01-05',1,2)",
                           (sid, ta, ua)),
        "study_session_steps": ("INSERT INTO study_session_steps (tenant_id, session_id, "
                                "user_id, step_no, kind, minutes, payload) "
                                "VALUES ($1,$2,$3,1,'learn',10,'{}')", (ta, sid, ua)),
        "weakness_events": ("INSERT INTO weakness_events (tenant_id, user_id, kind, ref_id, "
                            "question_id, retest_by) VALUES ($1,$2,'sba_wrong',$3,$4,now())",
                            (ta, ua, uuid4(), ids["questions"][0])),
    }


async def _rls_proof(runtime: Any, ids: dict[str, Any]) -> None:
    ids["session"] = uuid4()
    for table, (sql, args) in _inserts(ids).items():
        await _as_tenant(runtime, ids["ta"], sql, *args)
        assert await _as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}")) == 1, table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, ids["tb"], sql, *args)
        moved = await _as_tenant(
            runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 RETURNING 1", ids["tb"])
        assert moved == [], table
        assert await _as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1") == []
    for table in reversed(TABLES):
        await _as_tenant(runtime, ids["ta"], f"DELETE FROM {table}")


@asynccontextmanager
async def _repo(engine: Any, tenant: UUID) -> AsyncIterator[Any]:
    from apps.api.app.study.repo import SqlStudyRepo
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"),
                              {"t": str(tenant)})
        yield SqlStudyRepo(session, tenant)


def _step(view: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(s for s in view["steps"] if s["kind"] == kind)


async def _session_proof(engine: Any, ids: dict[str, Any], now: datetime) -> dict[str, Any]:
    from apps.api.app.study import sessions

    async with _repo(engine, ids["ta"]) as repo:
        view = await sessions.today_session(repo, ids["ua"], now)
    async with _repo(engine, ids["ta"]) as repo:
        again = await sessions.today_session(repo, ids["ua"], now)
    assert again["id"] == view["id"]
    kinds = [s["kind"] for s in view["steps"]]
    assert kinds == ["learn", "test", "viva"], kinds
    assert _step(view, "learn")["learn"]["chunks"][0]["citation"]["page_from"] == 1
    test = _step(view, "test")
    qid = test["test"]["questions"][0]["id"]
    async with _repo(engine, ids["ta"]) as repo:
        await sessions.start_step(repo, ids["ua"], view["id"], test["step_no"], now)
    async with _repo(engine, ids["ta"]) as repo:
        answered, _ = await sessions.answer(repo, ids["ua"], view["id"], test["step_no"], {
            "question_id": qid, "selected_option": 3, "confidence": 3}, now)
    feedback = _step(answered, "test")["test"]["results"][0]
    assert feedback["correct"] is False and feedback["key"] == 0
    return {"session_id": view["id"], "question_id": UUID(qid)}


async def _weakness_proof(engine: Any, runtime: Any, ids: dict[str, Any], now: datetime,
                          found: dict[str, Any]) -> None:
    from apps.api.app.assessment import exams
    from apps.api.app.study import weakness_sql

    rows = await _as_tenant(runtime, ids["ta"], "SELECT a.id, a.confidence FROM attempts a")
    assert [r["confidence"] for r in rows] == [3]
    cards = await _as_tenant(runtime, ids["ta"], "SELECT origin, state, due_at, citation "
                             "FROM cards WHERE origin = 'weakness'")
    assert len(cards) == 1 and cards[0]["state"] == "learning"
    assert cards[0]["due_at"] <= now + timedelta(days=2)
    events = await _as_tenant(runtime, ids["ta"], "SELECT kind, curriculum_code, retest_by "
                              "FROM weakness_events")
    assert [(e["kind"], e["curriculum_code"]) for e in events] == [("sba_wrong", "CHEST")]
    async with _repo(engine, ids["ta"]) as repo:
        question = (await repo.questions_by_ids(ids["ua"], [found["question_id"]]))[
            str(found["question_id"])]
        again = await weakness_sql.record_wrong(repo.session, ids["ta"], ids["ua"], question,
                                                "sba_wrong", rows[0]["id"], now)
        assert again is None  # idempotent per attempt
        exam = await repo._fetch(
            "INSERT INTO exams (tenant_id, user_id, mode, question_ids, answers) VALUES "
            "(:t, :u, 'practice', CAST(:q AS uuid[]), CAST(:a AS jsonb)) RETURNING id",
            {"t": ids["ta"], "u": ids["ua"], "q": [ids["questions"][-1]],
             "a": json.dumps({str(ids["questions"][-1]): 2})})
        await exams.submit(repo.session, ids["ta"], ids["ua"], exam[0]["id"])
        await repo.commit()
    kinds = await _as_tenant(runtime, ids["ta"], "SELECT kind FROM weakness_events ORDER BY kind")
    assert [k["kind"] for k in kinds] == ["exam_wrong", "sba_wrong"]


async def _finish_proof(engine: Any, ids: dict[str, Any], now: datetime,
                        found: dict[str, Any]) -> None:
    from apps.api.app.study import insights, sessions

    async with _repo(engine, ids["ta"]) as repo:
        done = await sessions.complete_session(repo, ids["ua"], found["session_id"], now)
    assert done["status"] == "completed" and "weighted_coverage" in done["summary"]
    async with _repo(engine, ids["ta"]) as repo:
        view = await insights.insights(repo, ids["ua"], now)
    assert view["calibration"]["rated"] == 1 and view["calibration"]["confident_wrong"] == 1
    assert any(row["code"] == "CHEST" for row in view["heatmap"])
    async with _repo(engine, ids["tb"]) as repo:
        assert await repo.get_session_by_id(ids["ua"], found["session_id"]) is None
        assert await repo.open_retests(ids["ua"], 10) == []
        assert await repo.rated_attempts(ids["ua"], now - timedelta(days=1)) == []
        assert await repo.coverage_stats(ids["ua"], now - timedelta(days=1)) == []


async def _service_proof(runtime_dsn: str, runtime: Any, ids: dict[str, Any]) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    now = datetime.now(UTC)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        found = await _session_proof(engine, ids, now)
        await _weakness_proof(engine, runtime, ids, now, found)
        await _finish_proof(engine, ids, now, found)
    finally:
        await engine.dispose()


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _rls_proof(runtime, ids)
        await _service_proof(runtime_dsn, runtime, ids)
    finally:
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_study_session_tables_and_weakness_loop_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
