"""Structured tables in the reader and in search, and the per-source re-process.

Tables come from ``source_tables`` (ADR 0030): rows with the table block's bbox
provenance, searchable through their tsvector. Every query is scoped to the
uploading user under RLS.

Re-process is owner-only (the uploader): it re-queues the source's latest
ingest job after resetting pages whose vision parse failed. The pipeline then
skips everything already done (succeeded steps, parsed pages, knowledge units
by content hash), rebuilds tables and chunks from stored blocks, and embeds
only text the tenant's embedding cache does not already hold, so unchanged
text is never paid for twice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BUSY_HOURS = 2


class ReprocessBusy(RuntimeError):
    """The source's pipeline is running right now."""


async def page_tables(session: AsyncSession, source_id: UUID, page_no: int) -> list[dict[str, Any]]:
    """Tables of one page (the caller has already proved it owns the page)."""
    rows = await session.execute(
        text("SELECT id, block_no, bbox, n_rows, n_cols, header, cells FROM source_tables "
             "WHERE source_id = :s AND page_no = :p ORDER BY block_no"),
        {"s": source_id, "p": page_no},
    )
    return [dict(r) for r in rows.mappings()]


async def search_tables(session: AsyncSession, user_id: UUID, query: str,
                        limit: int = 5) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT t.id, t.source_id, s.title AS source_title, t.page_no, t.block_no, t.bbox,
                   t.n_rows, t.n_cols, t.header, t.cells, ts_rank_cd(t.tsv, q) AS score
            FROM source_tables t
            JOIN sources s ON s.id = t.source_id AND s.tenant_id = t.tenant_id,
                 websearch_to_tsquery('english', :q) q
            WHERE t.tsv @@ q AND s.uploaded_by = :u AND s.deleted_at IS NULL
            ORDER BY score DESC, t.id
            LIMIT :n
            """
        ),
        {"q": query, "u": user_id, "n": limit},
    )
    return [{**dict(r), "score": float(r["score"])} for r in rows.mappings()]


async def request_reprocess(
    session: AsyncSession, principal: Principal, source_id: UUID
) -> dict[str, Any] | None:
    """Reset failed pages and mark the latest ingest job queued; None if not the owner's."""
    job = (await session.execute(
        text(
            "SELECT j.id, j.status, j.updated_at > now() - make_interval(hours => :h) AS fresh "
            "FROM jobs j JOIN sources s ON s.id = j.entity_id "
            "WHERE s.id = :s AND s.uploaded_by = :u AND s.deleted_at IS NULL "
            "AND j.kind = 'ingest_source' "
            "ORDER BY j.pipeline_version DESC, j.created_at DESC LIMIT 1"
        ),
        {"s": source_id, "u": principal.user_id, "h": BUSY_HOURS},
    )).mappings().first()
    if job is None:
        return None
    if job["status"] == "running" and job["fresh"]:
        raise ReprocessBusy("this source is being processed right now")
    retried: Any = await session.execute(
        text("UPDATE source_pages SET vision_status = 'pending' "
             "WHERE source_id = :s AND vision_status = 'failed'"),
        {"s": source_id},
    )
    await session.execute(
        text("UPDATE jobs SET status = 'queued', error_code = NULL WHERE id = :j"),
        {"j": job["id"]},
    )
    pages = int(retried.rowcount or 0)
    await audit(session, principal, "source.reprocess_requested", "source", str(source_id),
                {"job_id": str(job["id"]), "retried_pages": pages})
    await session.commit()
    return {"source_id": source_id, "job_id": job["id"], "retried_pages": pages}
