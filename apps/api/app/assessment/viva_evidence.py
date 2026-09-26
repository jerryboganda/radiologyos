"""Evidence for a viva or staged case: gathered once, stored as references only.

A session freezes *which* excerpts it uses (chunk and figure ids with their
provenance and labels), never a copy of the source text, so deleting a source
also removes the text a session can reach. Each worker step re-reads the text
from the caller's own live sources; an excerpt whose source was deleted simply
drops out, and a session left with no text excerpt stops (fail closed).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from apps.api.app.assessment import retrieval
from packages.assessment.validation import Excerpt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FIGURE_SQL = (
    "SELECT f.id, f.source_id, s.title AS source_title, f.page_no, f.caption, f.description, "
    "f.modality, f.anatomy, f.findings, f.bbox FROM figures f JOIN sources s "
    "ON s.id = f.source_id AND s.tenant_id = f.tenant_id WHERE f.id = ANY(:ids) "
    "AND s.uploaded_by = :u AND s.deleted_at IS NULL"
)
_CHUNK_SQL = (
    "SELECT c.id, c.text FROM chunks c JOIN sources s ON s.id = c.source_id "
    "AND s.tenant_id = c.tenant_id WHERE c.id = ANY(:ids) AND s.uploaded_by = :u "
    "AND s.deleted_at IS NULL"
)


def freeze(excerpts: Sequence[Excerpt]) -> list[dict[str, Any]]:
    """Reference-only evidence: label, heading, and provenance; no source text."""
    return [{"ref": e.ref, "heading": e.heading[:300], "citation": e.citation}
            for e in excerpts]


async def load_figure(
    session: AsyncSession, user_id: UUID, figure_id: UUID
) -> dict[str, Any] | None:
    rows = await session.execute(text(_FIGURE_SQL), {"ids": [figure_id], "u": user_id})
    row = rows.mappings().first()
    return dict(row) if row else None


async def hydrate(
    session: AsyncSession, user_id: UUID, frozen: Sequence[Mapping[str, Any]]
) -> list[Excerpt]:
    """Re-read the text behind frozen references from the owner's live sources."""
    chunk_ids = [UUID(f["citation"]["chunk_id"]) for f in frozen
                 if f["citation"].get("kind") == "chunk"]
    figure_ids = [UUID(f["citation"]["figure_id"]) for f in frozen
                  if f["citation"].get("kind") == "figure"]
    chunks: dict[str, str] = {}
    if chunk_ids:
        rows = await session.execute(text(_CHUNK_SQL), {"ids": chunk_ids, "u": user_id})
        chunks = {str(r["id"]): r["text"] for r in rows.mappings()}
    figures: dict[str, Excerpt] = {}
    if figure_ids:
        rows = await session.execute(text(_FIGURE_SQL), {"ids": figure_ids, "u": user_id})
        figures = {str(r["id"]): retrieval.figure_excerpt(dict(r)) for r in rows.mappings()}
    out: list[Excerpt] = []
    budget = retrieval.MAX_CHARS
    for item in frozen:
        cite = item["citation"]
        if cite.get("kind") == "figure" and cite.get("figure_id") in figures:
            fig = figures[cite["figure_id"]]
            out.append(Excerpt(item["ref"], fig.heading, fig.text, cite, fig.figure_id))
        elif cite.get("kind") == "chunk" and cite.get("chunk_id") in chunks and budget > 0:
            body = chunks[cite["chunk_id"]][:budget]
            budget -= len(body)
            out.append(Excerpt(item["ref"], item.get("heading", ""), body, cite))
    return out


def has_text(excerpts: Sequence[Excerpt]) -> bool:
    return any(e.ref.startswith("E") for e in excerpts)


def search_query(topic: str | None, figure: Mapping[str, Any] | None) -> str:
    """The text search behind a session: the topic, else the figure's caption and region."""
    if topic or figure is None:
        return topic or ""
    query = " ".join(str(figure.get(k) or "") for k in ("caption", "modality", "anatomy"))
    return query.strip()[:200] or str(figure.get("description") or "")[:200]


async def gather(
    session: AsyncSession, user_id: UUID, topic: str | None, figure: Mapping[str, Any] | None,
    vector: Sequence[float] | None, want_figure: bool, tenant_id: UUID | None = None,
) -> list[Excerpt]:
    """Text excerpts for the topic (or the figure's caption), led by the figure if any.

    With ``tenant_id`` the fused hits are reranked (ADR 0028, fail-open).
    """
    if figure is None:
        return await retrieval.gather_excerpts(session, user_id, topic, [], vector, want_figure,
                                               tenant_id=tenant_id)
    query = search_query(topic, figure)
    rows = await retrieval.topic_rows(session, user_id, query, [], vector, tenant_id)
    lead = retrieval.figure_excerpt(dict(figure))
    return [lead, *retrieval.chunk_excerpts(rows, retrieval.MAX_CHARS - len(lead.text))]
