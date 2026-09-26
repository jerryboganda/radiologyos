"""Reads and run bookkeeping for the knowledge worker (tenant session, RLS)."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def unit_hash(value: str) -> str:
    """Stable content hash for a chunk/page; the only content-derived value logged."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def load_source(session: AsyncSession, source_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, uploaded_by, title, status FROM sources "
                "WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": source_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def ingest_job(session: AsyncSession, source_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, entity_id, pipeline_version, status FROM jobs "
                "WHERE entity_id = :s AND kind = 'ingest_source' "
                "ORDER BY pipeline_version DESC, created_at DESC LIMIT 1"
            ),
            {"s": source_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def chunks(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, chunk_no, page_from, page_to, heading, text, block_refs FROM chunks "
            "WHERE source_id = :s ORDER BY chunk_no"
        ),
        {"s": source_id},
    )
    return [dict(row) for row in rows.mappings()]


async def blocks_for_pages(
    session: AsyncSession, source_id: UUID, page_from: int, page_to: int
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT page_no, block_no, text, bbox FROM source_blocks WHERE source_id = :s "
            "AND page_no BETWEEN :a AND :b ORDER BY page_no, block_no"
        ),
        {"s": source_id, "a": page_from, "b": page_to},
    )
    return [dict(row) for row in rows.mappings()]


async def page_texts(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    """Per page: parsed block text (reading order) or the native text layer."""
    rows = await session.execute(
        text(
            """
            SELECT p.page_no, p.image_key, p.native_text,
                   coalesce(string_agg(b.text, E'\\n' ORDER BY b.block_no), '') AS block_text
            FROM source_pages p
            LEFT JOIN source_blocks b ON b.source_id = p.source_id AND b.page_no = p.page_no
            WHERE p.source_id = :s
            GROUP BY p.page_no, p.image_key, p.native_text
            ORDER BY p.page_no
            """
        ),
        {"s": source_id},
    )
    return [
        {"page_no": r["page_no"], "image_key": r["image_key"],
         "text": r["block_text"] or r["native_text"] or ""}
        for r in rows.mappings()
    ]


async def run_done(
    session: AsyncSession, source_id: UUID, unit: str, agent: str, version: int
) -> bool:
    value = (
        await session.execute(
            text(
                "SELECT status FROM knowledge_runs WHERE source_id = :s AND unit = :u "
                "AND agent_version = :a AND pipeline_version = :v"
            ),
            {"s": source_id, "u": unit, "a": agent, "v": version},
        )
    ).scalar_one_or_none()
    return value in ("succeeded", "skipped")


async def record_run(
    session: AsyncSession, tenant_id: UUID, source_id: UUID, unit: str, agent: str,
    version: int, status: str, output_ref: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO knowledge_runs
                (tenant_id, source_id, unit, agent_version, pipeline_version, status, output_ref)
            VALUES (:t, :s, :u, :a, :v, :status, :out)
            ON CONFLICT (tenant_id, source_id, unit, agent_version, pipeline_version)
            DO UPDATE SET status = EXCLUDED.status, output_ref = EXCLUDED.output_ref
            """
        ),
        {"t": tenant_id, "s": source_id, "u": unit, "a": agent, "v": version,
         "status": status, "out": output_ref},
    )
