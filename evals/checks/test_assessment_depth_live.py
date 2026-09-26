"""Opt-in live proof for the assessment depth slice (migration 0011).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* ``item_stats`` and ``grading_jobs`` hide tenant A's rows from tenant B,
  reject writes with a foreign tenant_id, show nothing without tenant context,
  and cannot reference another tenant's question;
* trigram duplicate detection rejects a near-identical stem only inside the
  owner's tenant;
* a mixed SBA + SEQ exam autosaves text, grades SBA on submit, leaves the SEQ
  pending, and the worker grading step (fake transport) fills it in exactly
  once, appends the attempt, and recomputes item statistics;
* review approval requires the cited source page to still exist.
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
GRADE = {"points": [{"scheme_index": 0, "status": "matched", "awarded": 5,
                     "justification": "names the finding"}], "feedback": "Specific."}


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("assessment depth proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the depth proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


class GradeTransport:
    """Answers every call with one fixed ``seq_grade`` output."""

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def run(self, call: Any) -> Any:
        from packages.models.claude_code import ModelResult

        self.calls += 1
        return ModelResult(output=GRADE, duration_ms=1, cost_usd=0.0)


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "qa", "ea", "sa")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Depth A'),"
            "($2,'personal','Depth B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"depth-{ids[user]}", f"{ids[user]}@example.invalid")
        await admin.execute(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, title) "
            "VALUES ($1,$2,$3,'pdf','private',$4,'Synthetic')",
            ids["sa"], ids["ta"], ids["ua"], uuid4().hex + uuid4().hex)
        await admin.execute("INSERT INTO source_pages (tenant_id, source_id, page_no) "
                            "VALUES ($1,$2,2)", ids["ta"], ids["sa"])
        await admin.execute(
            "INSERT INTO questions (id, tenant_id, user_id, type, stem, answer, citations, "
            f"agent_version) VALUES ($1,$2,$3,'seq','Discuss.','{{}}','{CITE}','test/v1')",
            ids["qa"], ids["ta"], ids["ua"])
        await admin.execute(
            "INSERT INTO exams (id, tenant_id, user_id, mode, question_ids) "
            "VALUES ($1,$2,$3,'practice',ARRAY[$4]::uuid[])",
            ids["ea"], ids["ta"], ids["ua"], ids["qa"])
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("grading_jobs", "item_stats", "attempts", "exams", "questions",
                      "audit_log", "source_pages", "sources"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


INSERTS = {
    "item_stats": "INSERT INTO item_stats (tenant_id, user_id, question_id, attempts) "
                  "VALUES ($1,$2,$3,0)",
    "grading_jobs": "INSERT INTO grading_jobs (tenant_id, user_id, question_id, exam_id, "
                    "grader) VALUES ($1,$2,$3,$4,'seq_grade/v1')",
}


def _args(table: str, tenant: UUID, user: UUID, question: UUID, exam: UUID) -> list[Any]:
    return [tenant, user, question] + ([exam] if table == "grading_jobs" else [])


async def _rls_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb, ua, ub = ids["ta"], ids["tb"], ids["ua"], ids["ub"]
    for table, sql in INSERTS.items():
        await _as_tenant(runtime, ta, sql, *_args(table, ta, ua, ids["qa"], ids["ea"]))
        assert await _as_tenant(runtime, tb, f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ta, f"SELECT 1 FROM {table}")) == 1, table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, tb, sql, *_args(table, ta, ua, uuid4(), ids["ea"]))
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await _as_tenant(runtime, tb, sql, *_args(table, tb, ub, ids["qa"], ids["ea"]))
        moved = await _as_tenant(runtime, tb, f"UPDATE {table} SET tenant_id = $1 RETURNING 1", tb)
        assert moved == [], table
        assert await _as_tenant(runtime, tb, f"DELETE FROM {table} RETURNING 1") == [], table
        await _as_tenant(runtime, ta, f"DELETE FROM {table}")


def _question(kind: str, source: UUID, page: int, status: str = "active",
              stem: str | None = None) -> dict[str, Any]:
    cite = [{"ref": "E1", "kind": "chunk", "source_id": str(source), "page_from": page}]
    sba = kind == "sba"
    return {
        "type": kind, "exam_tags": ["frcr"], "topic": "Chest",
        "stem": stem or f"Pulmonary alveolar proteinosis {kind} stem {uuid4().hex[:6]}?",
        "options": [{"text": f"option {i}", "explanation": "e", "citations": cite}
                    for i in range(5)] if sba else [],
        "answer": {"key": 1} if sba else {
            "model_answer": "Crazy paving.", "key_findings": [], "viva_turns": [],
            "marking_scheme": [{"point": "crazy paving", "marks": 5, "citations": cite}]},
        "explanation": "x", "citations": cite, "figure_id": None, "status": status,
        "quality": {"passed": status == "active"}, "agent_version": "test/v1",
    }


async def _dedupe_proof(engine: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import dedupe, store
    from apps.worker.app.ingest.db import tenant_tx

    stem = "A 45-year-old smoker has crazy paving on HRCT. What is the most likely diagnosis?"
    async with tenant_tx(engine, ids["ta"]) as s:
        await store.insert_question(s, ids["ta"], ids["ua"], _question("sba", ids["sa"], 2,
                                                                        stem=stem))
        near = _question("sba", ids["sa"], 2, stem=stem.replace("45", "46"))
        fresh = _question("sba", ids["sa"], 2, stem="Which sign marks sarcoid nodes?")
        outcome = await dedupe.insert_unique(s, ids["ta"], ids["ua"], [(0, near), (1, fresh)],
                                             None, None)
        assert [index for index, _ in outcome.duplicates] == [0] and len(outcome.created) == 1
        assert outcome.duplicates[0][1].similarity >= 0.9
    async with tenant_tx(engine, ids["tb"]) as s:
        assert await dedupe.nearest_by_trigram(s, ids["ua"], stem) is None


async def _exam_proof(engine: Any, admin: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import exams, grading_store, store
    from apps.worker.app.assessment.grading import grade_item
    from apps.worker.app.ingest.db import tenant_tx
    from sqlalchemy import text

    ta, ua = ids["ta"], ids["ua"]
    async with tenant_tx(engine, ta) as s:
        sba = await store.insert_question(s, ta, ua, _question("sba", ids["sa"], 2))
        seq = await store.insert_question(s, ta, ua, _question("seq", ids["sa"], 2))
        await s.execute(text("UPDATE questions SET status = 'retired' WHERE id <> ALL(:keep)"),
                        {"keep": [sba, seq]})
        exam_id = await exams.create_exam(s, ta, ua, {
            "mode": "practice", "exam_target": "frcr", "topic": None, "count": 5,
            "time_limit_minutes": None, "types": ["sba", "seq"]})
    async with tenant_tx(engine, ta) as s:
        saved = await exams.save_answers(s, ua, exam_id, 0, {str(sba): 1},
                                         {str(seq): "Crazy paving in PAP."})
        assert saved is not None and saved["text_answers"] == {str(seq): "Crazy paving in PAP."}
        submitted = await exams.submit(s, ta, ua, exam_id)
    assert submitted is not None and submitted["result"]["pending"] == 1
    transport = GradeTransport()
    assert await grade_item(engine, transport, ta, exam_id, seq) == "graded"
    assert await grade_item(engine, transport, ta, exam_id, seq) == "done"
    assert await grade_item(engine, transport, ids["tb"], exam_id, seq) == "missing"
    assert transport.calls == 1
    async with tenant_tx(engine, ta) as s:
        final = await exams.load_exam(s, ua, exam_id)
        assert await grading_store.open_count(s, exam_id) == 0
    assert final is not None and final["result"]["grading"] == "complete"
    assert final["result"]["score"] == 6.0 and final["result"]["max_score"] == 6.0
    counted = await _as_tenant(admin, None, "SELECT count(*) FROM attempts WHERE exam_id = $1",
                               exam_id)
    stats = await _as_tenant(admin, None, "SELECT count(*) FROM item_stats WHERE tenant_id = $1",
                             ta)
    assert counted[0][0] == 2 and stats[0][0] == 2


async def _review_proof(engine: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import review, review_store, store
    from apps.api.app.security.principal import Principal
    from apps.worker.app.ingest.db import tenant_tx

    ta, ua = ids["ta"], ids["ua"]
    principal = Principal(user_id=ua, tenant_id=ta)
    async with tenant_tx(engine, ta) as s:
        good = await store.insert_question(s, ta, ua, _question("sba", ids["sa"], 2, "draft"))
        stale = await store.insert_question(s, ta, ua, _question("sba", ids["sa"], 99, "draft"))
        row = await review_store.get_for_review(s, ua, stale)
        assert row is not None
        with pytest.raises(review.ReviewRefused):
            await review.review(s, principal, row, "approve", {})
        row = await review_store.get_for_review(s, ua, good)
        assert row is not None
        updated = await review.review(s, principal, row, "approve", {})
        assert updated["status"] == "active"
    async with tenant_tx(engine, ids["tb"]) as s:
        assert await review_store.list_drafts(s, ua, 20, 0) == []
    async with tenant_tx(engine, ta) as s:
        assert [d["id"] for d in await review_store.list_drafts(s, ua, 20, 0)] == [stale]


async def _run() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        await _rls_proof(runtime, ids)
        await _dedupe_proof(engine, ids)
        await _exam_proof(engine, admin, ids)
        await _review_proof(engine, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_assessment_depth_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
