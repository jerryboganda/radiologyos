"""Select the numbered source excerpts a question is generated from.

A topic runs the library's hybrid search; source ids alone sample chunks from
those sources. Either way only the caller's own, non-deleted sources are used,
the excerpt budget is capped (spec section 9: at most ~6k tokens), and each
excerpt keeps the provenance its citations resolve to.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from apps.api.app.library import rerank, search
from packages.assessment.validation import Excerpt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_EXCERPTS = 8
MAX_CHARS = 24_000


async def _sample_chunks(
    session: AsyncSession, user_id: UUID, source_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT c.id, c.source_id, s.title AS source_title, c.page_from, c.page_to,
                   c.heading, c.text, c.block_refs
            FROM chunks c JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
            WHERE c.source_id = ANY(:ids) AND s.uploaded_by = :u AND s.deleted_at IS NULL
            ORDER BY random() LIMIT :n
            """
        ),
        {"ids": list(source_ids), "u": user_id, "n": MAX_EXCERPTS},
    )
    return [dict(row) for row in rows.mappings()]


async def _pick_figure(
    session: AsyncSession, user_id: UUID, topic: str | None, source_ids: Sequence[UUID]
) -> dict[str, Any] | None:
    if topic:
        figures = await search.search_figures(session, user_id, topic, limit=12)
        figures = [f for f in figures if not source_ids or f["source_id"] in source_ids]
        return next((f for f in figures if f["description"]), None)
    row = (
        await session.execute(
            text(
                """
                SELECT f.id, f.source_id, s.title AS source_title, f.page_no, f.caption,
                       f.description, f.modality, f.anatomy, f.findings, f.bbox
                FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id
                WHERE f.source_id = ANY(:ids) AND s.uploaded_by = :u
                  AND s.deleted_at IS NULL AND f.description <> ''
                ORDER BY random() LIMIT 1
                """
            ),
            {"ids": list(source_ids), "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def exact_figure(
    session: AsyncSession, user_id: UUID, figure_id: UUID
) -> dict[str, Any] | None:
    """One of the caller's own figures, for "quiz me on this figure" (ADR 0025)."""
    row = (
        await session.execute(
            text(
                """
                SELECT f.id, f.source_id, s.title AS source_title, f.page_no, f.caption,
                       f.description, f.modality, f.anatomy, f.findings, f.bbox
                FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id
                WHERE f.id = :id AND s.uploaded_by = :u AND s.deleted_at IS NULL
                """
            ),
            {"id": figure_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


def figure_topic(figure: dict[str, Any]) -> str:
    """A retrieval topic for a figure: its caption, else modality, anatomy, and description."""
    caption = " ".join(str(figure.get("caption") or "").split())
    if len(caption) >= 2:
        return caption[:200]
    parts = [figure.get("modality") or "", figure.get("anatomy") or "",
             figure.get("description") or ""]
    return " ".join(" ".join(parts).split())[:200] or "radiology figure"


def chunk_excerpts(rows: Sequence[dict[str, Any]], budget: int = MAX_CHARS) -> list[Excerpt]:
    excerpts: list[Excerpt] = []
    used = 0
    for row in rows[:MAX_EXCERPTS]:
        body = row["text"][: max(0, budget - used)]
        if not body:
            break
        used += len(body)
        excerpts.append(Excerpt(
            ref=f"E{len(excerpts) + 1}", heading=row["heading"], text=body,
            citation={"kind": "chunk", "chunk_id": str(row["id"]),
                      "source_id": str(row["source_id"]), "source_title": row["source_title"],
                      "page_from": row["page_from"], "page_to": row["page_to"],
                      "block_refs": row["block_refs"]},
        ))
    return excerpts


def figure_excerpt(row: dict[str, Any]) -> Excerpt:
    findings = row.get("findings") or []
    text_parts = [f"{row['modality']} {row['anatomy']}".strip(), row["description"]]
    if findings:
        text_parts.append("Findings: " + "; ".join(str(f) for f in findings))
    return Excerpt(
        ref="F1", heading=row["caption"], text="\n".join(p for p in text_parts if p),
        citation={"kind": "figure", "figure_id": str(row["id"]),
                  "source_id": str(row["source_id"]), "source_title": row["source_title"],
                  "page_no": row["page_no"], "bbox": list(row.get("bbox") or [])},
        figure_id=row["id"],
    )


async def topic_rows(
    session: AsyncSession, user_id: UUID, topic: str, source_ids: Sequence[UUID],
    query_vector: Sequence[float] | None, tenant_id: UUID | None,
) -> list[dict[str, Any]]:
    """Hybrid hits for a topic, source-filtered, then reranked when a tenant is given."""
    limit = MAX_EXCERPTS * 2
    pool = rerank.candidate_pool(limit) if tenant_id is not None else limit
    rows = await search.hybrid_search(session, user_id, topic, query_vector, pool)
    rows = [r for r in rows if not source_ids or r["source_id"] in source_ids]
    if tenant_id is None:
        return rows[:limit]
    return (await rerank.rerank_hits(tenant_id, topic, rows, limit)).hits


async def gather_excerpts(
    session: AsyncSession,
    user_id: UUID,
    topic: str | None,
    source_ids: Sequence[UUID],
    query_vector: Sequence[float] | None,
    with_figure: bool,
    figure: dict[str, Any] | None = None,
    tenant_id: UUID | None = None,
) -> list[Excerpt]:
    """Numbered excerpts; a given ``figure`` is always F1 (quiz on a figure).

    With ``tenant_id`` the topic's fused hits are reranked (ADR 0028, fail-open).
    """
    if topic:
        rows = await topic_rows(session, user_id, topic, source_ids, query_vector, tenant_id)
    else:
        rows = await _sample_chunks(session, user_id, source_ids)
    if figure is None and with_figure:
        figure = await _pick_figure(session, user_id, topic, source_ids)
    budget = MAX_CHARS
    excerpts: list[Excerpt] = []
    if figure is not None:
        excerpts.append(figure_excerpt(figure))
        budget -= len(excerpts[0].text)
    return excerpts + chunk_excerpts(rows, budget)
