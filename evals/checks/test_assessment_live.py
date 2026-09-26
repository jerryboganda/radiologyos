"""Opt-in live proof for the assessment tables and exam lifecycle (migration 0007).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* questions, exams, and attempts hide tenant A's rows from tenant B, reject
  writes with a foreign tenant_id, show nothing without tenant context, and a
  tenant cannot attach an attempt to another tenant's question;
* the real exam service creates a timed exam, autosaves with compare-and-set,
  hides keys while open, submits idempotently, and finalises an expired exam.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
CITE = '[{"ref":"E1","kind":"chunk","page_from":1}]'


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("assessment live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the assessment proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "qa")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Assess A'),"
            "($2,'personal','Assess B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"assess-{ids[user]}", f"{ids[user]}@example.invalid")
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("attempts", "exams", "questions"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


INSERTS = {
    "questions": "INSERT INTO questions (id, tenant_id, user_id, type, stem, answer, citations, "
                 "agent_version) VALUES ($3,$1,$2,'seq','Discuss.','{\"model_answer\":\"x\"}', "
                 f"'{CITE}','test/v1')",
    "exams": "INSERT INTO exams (tenant_id, user_id, mode, question_ids) "
             "VALUES ($1,$2,'practice',ARRAY[$3]::uuid[])",
    "attempts": "INSERT INTO attempts (tenant_id, user_id, question_id, response, score, "
                "max_score, graded_by) VALUES ($1,$2,$3,'{}',0,1,'rule:test')",
}


async def _table_proof(runtime: Any, ids: dict[str, UUID], table: str, sql: str) -> None:
    ta, tb = ids["ta"], ids["tb"]
    await _as_tenant(runtime, ta, sql, ta, ids["ua"], ids["qa"])
    assert await _as_tenant(runtime, tb, f"SELECT 1 FROM {table}") == [], table
    assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
    assert len(await _as_tenant(runtime, ta, f"SELECT 1 FROM {table}")) == 1, table
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, sql, ta, ids["ua"], uuid4())
    if table == "attempts":  # append-only for the runtime role
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, ta, "UPDATE attempts SET score = 1 RETURNING 1")
    else:
        moved = await _as_tenant(
            runtime, tb, f"UPDATE {table} SET tenant_id = $1 RETURNING 1", tb)
        assert moved == [], table
    assert await _as_tenant(runtime, tb, f"DELETE FROM {table} RETURNING 1") == [], table


async def _rls_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    for table, sql in INSERTS.items():
        await _table_proof(runtime, ids, table, sql)
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await _as_tenant(runtime, ids["tb"], INSERTS["attempts"], ids["tb"], ids["ub"], ids["qa"])
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(
            runtime, ids["ta"], INSERTS["questions"].replace(CITE, "[]"),
            ids["ta"], ids["ua"], uuid4())
    await _as_tenant(runtime, ids["ta"], "DELETE FROM attempts")
    await _as_tenant(runtime, ids["ta"], "DELETE FROM exams")


def _sba(topic: str) -> dict[str, Any]:
    cite = [{"ref": "E1", "kind": "chunk", "page_from": 1}]
    return {
        "type": "sba", "exam_tags": ["fcps2_theory"], "topic": topic, "stem": f"{topic}?",
        "options": [{"text": f"o{i}", "explanation": "e", "citations": cite} for i in range(5)],
        "answer": {"key": 1}, "explanation": "x", "citations": cite, "figure_id": None,
        "status": "active", "quality": {"passed": True}, "agent_version": "test/v1",
    }


async def _exam_proof(engine: Any, admin: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import exams, store
    from apps.worker.app.ingest.db import tenant_tx
    from packages.assessment.grading import ExamExpired, StaleRevision

    ta, ua = ids["ta"], ids["ua"]
    async with tenant_tx(engine, ta) as s:
        qids = [await store.insert_question(s, ta, ua, _sba(t)) for t in ("Chest", "Neuro")]
        config = {"mode": "exam", "exam_target": "fcps2_theory", "topic": None, "count": 5,
                  "time_limit_minutes": 30}
        exam_id = await exams.create_exam(s, ta, ua, config)
    async with tenant_tx(engine, ta) as s:
        assert await store.in_open_exam(s, ua, qids[0])
        saved = await exams.save_answers(s, ua, exam_id, 0, {str(qids[0]): 1})
        assert saved is not None and saved["revision"] == 1
        with pytest.raises(StaleRevision):
            await exams.save_answers(s, ua, exam_id, 0, {str(qids[1]): 2})
    async with tenant_tx(engine, ids["tb"]) as s:
        assert await exams.load_exam(s, ua, exam_id) is None
        assert await exams.submit(s, ids["tb"], ids["ub"], exam_id) is None
    async with tenant_tx(engine, ta) as s:
        first = await exams.submit(s, ta, ua, exam_id)
    async with tenant_tx(engine, ta) as s:
        again = await exams.submit(s, ta, ua, exam_id)
        assert not await store.in_open_exam(s, ua, qids[0])
    assert first is not None and again is not None
    assert first["result"]["score"] == again["result"]["score"] == 1.0
    assert first["result"]["max_score"] == 2.0 and not first["result"]["timed_out"]
    counted = await _as_tenant(admin, None, "SELECT count(*) FROM attempts WHERE exam_id = $1",
                               exam_id)
    assert counted[0][0] == 2
    await _expiry_proof(engine, admin, ids, config, exams, ExamExpired)


async def _expiry_proof(
    engine: Any, admin: Any, ids: dict[str, UUID], config: dict[str, Any], exams: Any,
    expired_error: type[Exception],
) -> None:
    from apps.worker.app.ingest.db import tenant_tx

    ta, ua = ids["ta"], ids["ua"]
    async with tenant_tx(engine, ta) as s:
        exam_id = await exams.create_exam(s, ta, ua, config)
    await admin.execute(
        "UPDATE exams SET started_at = now() - interval '2 hours', "
        "deadline_at = now() - interval '1 hour' WHERE id = $1", exam_id)
    async with tenant_tx(engine, ta) as s:
        with pytest.raises(expired_error):
            await exams.save_answers(s, ua, exam_id, 0, {})
    async with tenant_tx(engine, ta) as s:
        final = await exams.read_exam(s, ta, ua, exam_id)
    assert final is not None and final["result"]["timed_out"] is True
    assert final["result"]["answered"] == 0


async def _run() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        await _rls_proof(runtime, ids)
        await _exam_proof(engine, admin, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_assessment_tables_and_exam_lifecycle_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
