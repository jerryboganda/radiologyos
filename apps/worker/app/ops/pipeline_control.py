"""Owner controls for the library pipeline (ADR 0037): status, approve, relaunch.

Shared by the pipeline CLI and the ``radbrain.approve_escalations`` task that
Settings triggers. Every statement runs in the owner's tenant transaction (RLS)
and prints or returns counts and ids only - never source text.

* ``status``   - pause state, page/job/knowledge progress, items awaiting approval.
* ``approve``  - pending items become approved: their pages are queued for a
  re-read and their knowledge units for re-extraction, which then run on
  Claude Opus 5.5 high only (the gateway's ``owner_approved``).
* ``dismiss``  - pending items are closed without spending Claude.
* ``relaunch`` - re-queue every unfinished ingest job and knowledge pass from
  the saved state, so a stopped or lost queue resumes where it left off.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.worker.app.celery_app import celery_app
from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge.enqueue import enqueue_knowledge
from packages.pipeline import state
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

MINE = "SELECT id FROM sources WHERE uploaded_by = :u AND deleted_at IS NULL"
PAGE_AGENTS = ("page_parse", "image_case")
STATUS_SQL = {
    "pages": f"SELECT vision_status AS k, count(*) AS n FROM source_pages "
             f"WHERE source_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
    "jobs": f"SELECT status AS k, count(*) AS n FROM jobs WHERE kind = 'ingest_source' "
            f"AND entity_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
    "knowledge_units": f"SELECT status AS k, count(*) AS n FROM knowledge_runs "
                       f"WHERE source_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
    "awaiting_owner": f"SELECT agent AS k, count(*) AS n FROM model_escalations "
                      f"WHERE status = 'pending' AND source_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
}  # nosec B608 - constant SQL built from the constant MINE subquery
UNFINISHED_KNOWLEDGE = f"""
    SELECT DISTINCT j.entity_id FROM jobs j JOIN job_steps st ON st.job_id = j.id
    WHERE j.kind = 'ingest_source' AND j.status = 'succeeded' AND j.entity_id IN ({MINE})
      AND st.step = 'knowledge_extraction' AND st.status <> 'succeeded'
"""  # nosec B608 - constant SQL
LATEST_JOBS = """
    SELECT DISTINCT ON (entity_id) id FROM jobs
    WHERE kind = 'ingest_source' AND entity_id = ANY(:ids) ORDER BY entity_id, created_at DESC
"""


async def status(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    current = state.current()
    out: dict[str, Any] = {"paused": current.reason, "resume_at": current.until,
                           "provider": current.provider, "claude_only": state.claude_only()}
    async with tenant_tx(engine, tenant_id) as session:
        for name, sql in STATUS_SQL.items():
            rows = await session.execute(text(sql), {"u": user_id})
            out[name] = {str(r.k): int(r.n) for r in rows}
    return out


async def approve(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> dict[str, int]:
    """Approve every pending item and queue its redo on the approval-gated target."""
    async with tenant_tx(engine, tenant_id) as session:
        result = await session.execute(text(
            f"UPDATE model_escalations SET status = 'approved' WHERE status = 'pending' "
            f"AND source_id IN ({MINE}) RETURNING source_id, agent, unit"),  # nosec B608
            {"u": user_id})
        rows = [(UUID(str(s)), str(a), str(u)) for s, a, u in result.all()]
        page_sources: set[UUID] = set()
        for source_id, agent, unit in rows:
            if agent in PAGE_AGENTS and unit.startswith("page:"):
                await session.execute(
                    text("UPDATE source_pages SET vision_status = 'pending' "
                         "WHERE source_id = :s AND page_no = :p"),
                    {"s": source_id, "p": int(unit.split(":", 1)[1])})
                page_sources.add(source_id)
        jobs = (await session.execute(text(LATEST_JOBS), {"ids": list(page_sources)})).all()
    for (job_id,) in jobs:
        celery_app.send_task("radbrain.ingest_source", args=[str(tenant_id), str(job_id)])
    knowledge = {s for s, agent, _ in rows if agent not in PAGE_AGENTS}
    if knowledge:  # re-opens finished knowledge passes too, so the redo really runs
        from apps.worker.app.ops.red_list_ops import redo_approved

        await redo_approved(engine, tenant_id, user_id)
    return {"approved": len(rows), "page_jobs": len(jobs), "knowledge_sources": len(knowledge)}


async def dismiss(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> int:
    async with tenant_tx(engine, tenant_id) as session:
        done = await session.execute(text(
            f"UPDATE model_escalations SET status = 'dismissed', resolved_at = now() "
            f"WHERE status = 'pending' AND source_id IN ({MINE})"), {"u": user_id})  # nosec B608
    return int(getattr(done, "rowcount", 0) or 0)


async def requeue_knowledge(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> int:
    """Knowledge passes whose task was lost (a restart, a purge) are queued again."""
    async with tenant_tx(engine, tenant_id) as session:
        sources = (await session.execute(text(UNFINISHED_KNOWLEDGE), {"u": user_id})).all()
    for (source_id,) in sources:
        enqueue_knowledge(tenant_id, UUID(str(source_id)))
    return len(sources)


# The owner's red list (ADR 0038), filled once for work done before it existed:
# items Opus already redid (their "kept although short" flag was not stored per
# item, so all are listed), pages every model failed, and knowledge units every
# model failed. Idempotent: rows already on the list keep their state.
BACKFILL = (
    f"UPDATE model_escalations SET status = 'review', resolved_at = NULL "
    f"WHERE status = 'done' AND source_id IN ({MINE})",  # nosec B608 - constant SQL
    f"INSERT INTO model_escalations (tenant_id, source_id, agent, unit, reason, status) "
    f"SELECT p.tenant_id, p.source_id, 'page_parse', 'page:' || p.page_no, "
    f"'all_models_failed', 'review' FROM source_pages p "
    f"WHERE p.vision_status = 'failed' AND p.source_id IN ({MINE}) "  # nosec B608
    f"ON CONFLICT (tenant_id, source_id, agent, unit) DO NOTHING",
    f"INSERT INTO model_escalations (tenant_id, source_id, agent, unit, reason, status) "
    f"SELECT DISTINCT r.tenant_id, r.source_id, 'knowledge_extract', r.unit, "
    f"'all_models_failed', 'review' FROM knowledge_runs r "
    f"WHERE r.status = 'failed' AND r.output_ref = 'model_error' "
    f"AND r.source_id IN ({MINE}) "  # nosec B608 - constant SQL
    f"ON CONFLICT (tenant_id, source_id, agent, unit) DO NOTHING",
)


async def backfill_red_list(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> int:
    async with tenant_tx(engine, tenant_id) as session:
        for sql in BACKFILL:
            await session.execute(text(sql), {"u": user_id})
        count = await session.execute(text(
            f"SELECT count(*) FROM model_escalations WHERE status = 'review' "
            f"AND source_id IN ({MINE})"), {"u": user_id})  # nosec B608 - constant SQL
        return int(count.scalar_one())
