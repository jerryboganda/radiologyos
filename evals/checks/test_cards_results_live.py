"""Opt-in live proof for cloze/image cards, results review, and disputes (migration 0102).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* ``grade_disputes`` hides tenant A's rows from tenant B, rejects a foreign
  tenant_id, shows nothing without tenant context, cannot attach to another
  tenant's exam, and goes with its exam;
* a cloze card is made from tenant A's claim (cited to the evidence blocks) and
  an image card from its figure, each once; tenant B sees no candidates and cannot
  point a card at tenant A's claim;
* an exam autosave keeps per-item seconds and confidence, and reading a stale
  exam re-queues a dead grading run but never refreshes a live run's lease.
All content is synthetic.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
CITE = json.dumps([{"kind": "chunk", "source_id": "x", "page_from": 2}])
CLAIM_CITATION = json.dumps({"blocks": [{"page_no": 2, "block_no": 1, "bbox": [0, 0, 1, 1]}]})
DISPUTE_SQL = ("INSERT INTO grade_disputes (tenant_id, user_id, exam_id, question_id, "
               "point_index, reason, marks, awarded_before) VALUES ($1,$2,$3,$4,0,'r',2,0) "
               "RETURNING id")


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("cards/results proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the cards proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _seed_people(admin: Any, ids: dict[str, UUID]) -> None:
    await admin.execute("INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Cards A'),"
                        "($2,'personal','Cards B')", ids["ta"], ids["tb"])
    for user, tenant in (("ua", "ta"), ("ub", "tb")):
        await admin.execute(
            "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
            ids[user], ids[tenant], f"cards-{ids[user]}", f"{ids[user]}@example.invalid")
    for source, tenant, user in (("sa", "ta", "ua"), ("sb", "tb", "ub")):
        await admin.execute(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, title) "
            "VALUES ($1,$2,$3,'pdf','private',$4,'Synthetic chest')",
            ids[source], ids[tenant], ids[user], uuid4().hex + uuid4().hex)


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "sb", "qa", "ea", "eb", "qb")}
    async with admin.transaction():
        await _seed_people(admin, ids)
        ids["concept"] = await admin.fetchval(
            "INSERT INTO concepts (tenant_id, name, normalized_name, aliases, alias_keys) "
            "VALUES ($1,'Pulmonary alveolar proteinosis','pulmonary alveolar proteinosis',"
            "'{PAP}','{pap}') RETURNING id", ids["ta"])
        ids["claim"] = await admin.fetchval(
            "INSERT INTO claims (tenant_id, concept_id, statement, evidence_span, source_id, "
            "page_from, page_to, citation, agent_version) VALUES ($1,$2,"
            "'Pulmonary alveolar proteinosis shows crazy paving on HRCT.',"
            "'crazy paving on HRCT',$3,2,2,$4::jsonb,'test/v1') RETURNING id",
            ids["ta"], ids["concept"], ids["sa"], CLAIM_CITATION)
        ids["figure"] = await admin.fetchval(
            "INSERT INTO figures (tenant_id, source_id, page_no, figure_no, bbox, caption, "
            "description, modality) VALUES ($1,$2,2,0,'{0,0,1,1}','Figure 1: PAP',"
            "'Geographic ground-glass with septal thickening','CT') RETURNING id",
            ids["ta"], ids["sa"])
        for q, e, t, u in (("qa", "ea", "ta", "ua"), ("qb", "eb", "tb", "ub")):
            await admin.execute(
                "INSERT INTO questions (id, tenant_id, user_id, type, stem, answer, citations, "
                f"agent_version) VALUES ($1,$2,$3,'seq','Discuss.','{{}}','{CITE}','test/v1')",
                ids[q], ids[t], ids[u])
            await admin.execute(
                "INSERT INTO exams (id, tenant_id, user_id, mode, question_ids) "
                "VALUES ($1,$2,$3,'practice',ARRAY[$4]::uuid[])", ids[e], ids[t], ids[u], ids[q])
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("grade_disputes", "grading_jobs", "card_reviews", "cards", "attempts",
                      "exams", "questions", "claims", "concepts", "figures", "audit_log",
                      "sources", "users"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _dispute_rls(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb, ua, ub = ids["ta"], ids["tb"], ids["ua"], ids["ub"]
    await _as_tenant(runtime, ta, DISPUTE_SQL, ta, ua, ids["ea"], ids["qa"])
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM grade_disputes") == []
    assert await _as_tenant(runtime, None, "SELECT 1 FROM grade_disputes") == []
    assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM grade_disputes")) == 1
    moved = await _as_tenant(runtime, tb, "UPDATE grade_disputes SET tenant_id = $1 RETURNING 1",
                             tb)
    assert moved == [] and await _as_tenant(
        runtime, tb, "DELETE FROM grade_disputes RETURNING 1") == []
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, DISPUTE_SQL, ta, ua, ids["ea"], ids["qa"])
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await _as_tenant(runtime, tb, DISPUTE_SQL, tb, ub, ids["ea"], ids["qb"])
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await _as_tenant(runtime, ta, DISPUTE_SQL, ta, ua, ids["ea"], ids["qa"])
    other = await _as_tenant(runtime, tb, DISPUTE_SQL, tb, ub, ids["eb"], ids["qb"])
    assert other and await _as_tenant(runtime, tb, "DELETE FROM exams WHERE id = $1 RETURNING 1",
                                      ids["eb"])
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM grade_disputes") == []


async def _generate(engine: Any, tenant: UUID, user: UUID, kind: str) -> dict[str, Any]:
    """Run the card use case as the API does: one tenant session, committed once."""
    from apps.api.app.core.time import now_utc
    from apps.api.app.study import knowledge_cards
    from apps.api.app.study.repo import SqlStudyRepo
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine, expire_on_commit=False) as db:
        repo = SqlStudyRepo(db, tenant)
        await repo.rebind()
        return await knowledge_cards.generate(repo, user, kind,  # type: ignore[arg-type]
                                              None, None, 5, now_utc())


async def _cards_flow(engine: Any, runtime: Any, ids: dict[str, UUID]) -> None:
    for kind in ("cloze", "image"):
        made = await _generate(engine, ids["ta"], ids["ua"], kind)
        assert len(made["created"]) == 1, kind
        card = made["created"][0]
        assert card["card_type"] == kind and card["citation"]["source_id"] == str(ids["sa"])
        again = await _generate(engine, ids["ta"], ids["ua"], kind)
        assert again["created"] == [] and again["considered"] == 0, kind
        other = await _generate(engine, ids["tb"], ids["ub"], kind)
        assert other["considered"] == 0, kind
    cloze = await _as_tenant(runtime, ids["ta"], "SELECT citation FROM cards WHERE claim_id = $1",
                             ids["claim"])
    assert json.loads(cloze[0][0])["block_refs"] == [{"page": 2, "block": 1}]
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await _as_tenant(
            runtime, ids["tb"],
            "INSERT INTO cards (tenant_id, user_id, source_id, curriculum_code, topic, front, "
            "back, citation, claim_id) SELECT $1, $2, $3, 'CHEST', 't', 'f', 'b', "
            "jsonb_build_object('source_id', $5::text, 'page_from', 1, 'page_to', 1), $4",
            ids["tb"], ids["ub"], ids["sb"], ids["claim"], str(ids["sb"]))


async def _review_flow(engine: Any, admin: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import exams, grading_store
    from apps.worker.app.ingest.db import tenant_tx
    from sqlalchemy import text

    qid = str(ids["qa"])
    async with tenant_tx(engine, ids["ta"]) as db:
        saved = await exams.save_answers(db, ids["ua"], ids["ea"], 0, {}, {qid: "PAP"},
                                         {"item_seconds": {qid: 5}, "confidence": {qid: 2}})
    assert saved is not None and saved["confidence"] == {qid: 2}
    assert saved["item_seconds"][qid] <= 65
    async with tenant_tx(engine, ids["ta"]) as db:
        await grading_store.create_job(db, ids["ta"], ids["ua"], ids["ea"], ids["qa"])
        await db.execute(text("UPDATE grading_jobs SET status = 'running' WHERE exam_id = :e"),
                         {"e": ids["ea"]})
    stamp = "SELECT updated_at FROM grading_jobs WHERE exam_id = $1"
    started = await admin.fetchval(stamp, ids["ea"])
    # A reader 12 minutes into the run: past the 10-minute re-queue mark, inside the
    # 15-minute takeover window. The live run must not be touched (its lease stays).
    async with tenant_tx(engine, ids["ta"]) as db:
        assert await grading_store.stale_pending(
            db, ids["ua"], ids["ea"], started + timedelta(minutes=2),
            started - timedelta(minutes=3)) == []
    assert await admin.fetchval(stamp, ids["ea"]) == started
    # A reader 20 minutes in: the silent run is handed back as pending for re-queueing.
    async with tenant_tx(engine, ids["ta"]) as db:
        requeued = await grading_store.stale_pending(
            db, ids["ua"], ids["ea"], started + timedelta(minutes=10),
            started + timedelta(minutes=5))
    assert requeued == [ids["qa"]]
    status = await admin.fetchval("SELECT status FROM grading_jobs WHERE exam_id = $1", ids["ea"])
    assert status == "pending"


async def _run() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        await _dispute_rls(runtime, ids)
        await _cards_flow(engine, runtime, ids)
        await _review_flow(engine, admin, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_cards_results_and_disputes_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
