"""Figure, chunk, and embedding persistence for the ingestion worker."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from apps.worker.app.ingest.db import as_json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def pages(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT page_no, image_key, native_text, vision_status, width, height "
            "FROM source_pages WHERE source_id = :s ORDER BY page_no"
        ),
        {"s": source_id},
    )
    return [dict(row) for row in rows.mappings()]


async def page_texts(
    session: AsyncSession, source_id: UUID, first: int, last: int
) -> dict[int, str]:
    """Page text in a range: parsed blocks where a page has them, else its native layer."""
    rows = await session.execute(
        text(
            "SELECT p.page_no, COALESCE((SELECT string_agg(b.text, ' ' ORDER BY b.block_no) "
            "FROM source_blocks b WHERE b.source_id = p.source_id AND b.page_no = p.page_no), "
            "p.native_text, '') AS text FROM source_pages p "
            "WHERE p.source_id = :s AND p.page_no BETWEEN :a AND :b"
        ),
        {"s": source_id, "a": first, "b": last},
    )
    return {int(row.page_no): str(row.text) for row in rows}


async def blocks(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT page_no, block_no, kind, text FROM source_blocks "
            "WHERE source_id = :s ORDER BY page_no, block_no"
        ),
        {"s": source_id},
    )
    return [dict(row) for row in rows.mappings()]


async def set_vision_status(
    session: AsyncSession, source_id: UUID, page_no: int, status: str, origin: str | None = None
) -> None:
    await session.execute(
        text(
            "UPDATE source_pages SET vision_status = :status, "
            "text_origin = COALESCE(:origin, text_origin) "
            "WHERE source_id = :s AND page_no = :p"
        ),
        {"s": source_id, "p": page_no, "status": status, "origin": origin},
    )


async def replace_figures(
    session: AsyncSession,
    tenant_id: UUID,
    source_id: UUID,
    page_no: int,
    figures: Sequence[dict[str, Any]],
) -> None:
    await session.execute(
        text("DELETE FROM figures WHERE source_id = :s AND page_no = :p"),
        {"s": source_id, "p": page_no},
    )
    for figure in figures:
        await session.execute(
            text(
                "INSERT INTO figures (tenant_id, source_id, page_no, figure_no, bbox, image_key, "
                "caption, description, modality, anatomy, findings, impression_origin, "
                "source_quote) VALUES "
                "(:t, :s, :p, :n, :bbox, :key, :caption, :description, :modality, :anatomy, "
                "CAST(:findings AS jsonb), :origin, :quote)"
            ),
            {
                "t": tenant_id, "s": source_id, "p": page_no, "n": figure["figure_no"],
                "bbox": list(figure["bbox"]), "key": figure.get("image_key"),
                "caption": figure.get("caption", ""),
                "description": figure.get("description", ""),
                "modality": figure.get("modality", ""),
                "anatomy": figure.get("anatomy", ""),
                "findings": as_json(figure.get("findings", [])),
                "origin": figure.get("impression_origin"),
                "quote": figure.get("source_quote"),
            },
        )


async def radiology_figures(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, page_no, figure_no, image_key, caption FROM figures "
            "WHERE source_id = :s AND image_key IS NOT NULL AND modality <> '' "
            "AND lower(modality) NOT LIKE '%diagram%' ORDER BY page_no, figure_no"
        ),
        {"s": source_id},
    )
    return [dict(row) for row in rows.mappings()]


async def enrich_figure(session: AsyncSession, figure_id: UUID, values: dict[str, Any]) -> None:
    await session.execute(
        text(
            "UPDATE figures SET description = :description, modality = :modality, "
            "anatomy = :anatomy, findings = CAST(:findings AS jsonb) WHERE id = :id"
        ),
        {
            "id": figure_id,
            "description": values["description"],
            "modality": values["modality"],
            "anatomy": values["anatomy"],
            "findings": as_json(values["findings"]),
        },
    )


async def replace_chunks(
    session: AsyncSession, tenant_id: UUID, source_id: UUID, chunks: Sequence[Any]
) -> int:
    await session.execute(text("DELETE FROM chunks WHERE source_id = :s"), {"s": source_id})
    for chunk in chunks:
        await session.execute(
            text(
                "INSERT INTO chunks (tenant_id, source_id, chunk_no, page_from, page_to, "
                "heading, text, block_refs) VALUES (:t, :s, :n, :pf, :pt, :h, :text, "
                "CAST(:refs AS jsonb))"
            ),
            {
                "t": tenant_id, "s": source_id, "n": chunk.chunk_no, "pf": chunk.page_from,
                "pt": chunk.page_to, "h": chunk.heading, "text": chunk.text,
                "refs": as_json(chunk.block_refs),
            },
        )
    return len(chunks)


async def unembedded_chunks(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, heading, text FROM chunks WHERE source_id = :s "
            "AND embedding IS NULL ORDER BY chunk_no"
        ),
        {"s": source_id},
    )
    return [dict(row) for row in rows.mappings()]


async def set_embedding(
    session: AsyncSession, chunk_id: UUID, vector: Sequence[float], model: str
) -> None:
    literal = "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
    await session.execute(
        text(
            "UPDATE chunks SET embedding = CAST(:v AS vector), embed_model = :m WHERE id = :id"
        ),
        {"id": chunk_id, "v": literal, "m": model},
    )
