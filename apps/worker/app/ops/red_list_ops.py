"""Finish the owner's approved Opus work and keep the red list current (ADR 0041).

* ``redo_approved`` - note sections the owner approved for Claude Opus 5.5 high
  but whose knowledge pass had already finished, so they were never redone. An
  approved unit that has since succeeded is closed as done; one whose section no
  longer exists (the page was re-read and re-chunked) is closed as dismissed; the
  rest have their source's knowledge pass re-opened and queued, and run on Opus.
* ``prune`` - red items fixed since they were listed leave the list: a page every
  model failed that has since been read, and a note section every model failed
  (or whose section no longer exists) that has since been extracted.

Counts and ids only; the owner's own verdicts are never touched.
"""

from __future__ import annotations

from uuid import UUID

from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge.enqueue import enqueue_knowledge
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

MINE = "SELECT id FROM sources WHERE uploaded_by = :u AND deleted_at IS NULL"
CHUNK_EXISTS = (
    "EXISTS (SELECT 1 FROM chunks c WHERE c.source_id = e.source_id AND 'chunk:' || "
    "left(encode(sha256(convert_to(c.text, 'UTF8')), 'hex'), 32) = e.unit)"
)
UNIT_SUCCEEDED = (
    "EXISTS (SELECT 1 FROM knowledge_runs r WHERE r.source_id = e.source_id "
    "AND r.unit = e.unit AND r.status = 'succeeded')"
)
APPROVED = f"e.agent = 'knowledge_extract' AND e.status = 'approved' AND e.source_id IN ({MINE})"
CLOSE_APPROVED = (
    f"UPDATE model_escalations e SET status = 'done', resolved_at = now() "
    f"WHERE {APPROVED} AND {UNIT_SUCCEEDED}",  # nosec B608 - constant SQL
    f"UPDATE model_escalations e SET status = 'dismissed', resolved_at = now() "
    f"WHERE {APPROVED} AND NOT {CHUNK_EXISTS}",  # nosec B608 - constant SQL
)
REOPEN = f"""
    UPDATE job_steps st SET status = 'pending', error_code = 'owner_approved_redo'
    FROM (SELECT DISTINCT ON (entity_id) id, entity_id FROM jobs
          WHERE kind = 'ingest_source' AND entity_id IN (
              SELECT e.source_id FROM model_escalations e WHERE {APPROVED})
          ORDER BY entity_id, created_at DESC) j
    WHERE st.job_id = j.id AND st.step = 'knowledge_extraction' AND st.status <> 'running'
    RETURNING j.entity_id
"""  # nosec B608 - constant SQL
FIXED = (
    f"UPDATE model_escalations e SET status = 'done', resolved_at = now() "
    f"WHERE e.status = 'review' AND e.owner_verdict IS NULL AND e.source_id IN ({MINE}) "
    f"AND e.agent = 'page_parse' AND e.reason = 'all_models_failed' AND EXISTS ("
    f"SELECT 1 FROM source_pages p WHERE p.source_id = e.source_id "
    f"AND 'page:' || p.page_no = e.unit AND p.vision_status = 'done')",  # nosec B608
    f"UPDATE model_escalations e SET status = 'done', resolved_at = now() "
    f"WHERE e.status = 'review' AND e.owner_verdict IS NULL AND e.source_id IN ({MINE}) "
    f"AND e.agent = 'knowledge_extract' AND ((e.reason = 'all_models_failed' "
    f"AND {UNIT_SUCCEEDED}) OR NOT {CHUNK_EXISTS})",  # nosec B608 - constant SQL
)


async def redo_approved(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> dict[str, int]:
    """Queue every approved note section that never got its Opus redo."""
    params = {"u": user_id}
    async with tenant_tx(engine, tenant_id) as session:
        done, stale = [
            int(getattr(await session.execute(text(sql), params), "rowcount", 0) or 0)
            for sql in CLOSE_APPROVED]
        sources = {UUID(str(r[0])) for r in (await session.execute(text(REOPEN), params)).all()}
        waiting = int((await session.execute(text(
            f"SELECT count(*) FROM model_escalations e WHERE {APPROVED}"),  # nosec B608
            params)).scalar_one())
    for source_id in sources:
        enqueue_knowledge(tenant_id, source_id)
    return {"already_done": done, "section_gone": stale, "queued_for_opus": waiting,
            "sources": len(sources)}


async def prune(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> int:
    """Take items fixed since they were listed off the red list; returns how many."""
    fixed = 0
    async with tenant_tx(engine, tenant_id) as session:
        for sql in FIXED:
            result = await session.execute(text(sql), {"u": user_id})
            fixed += int(getattr(result, "rowcount", 0) or 0)
    return fixed
