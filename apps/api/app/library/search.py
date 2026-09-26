"""Hybrid cited retrieval over the caller's own library (spec section 6).

Lexical (tsvector) and dense (pgvector cosine) candidates are fused with
reciprocal rank fusion (k=60). Every hit carries its citation: source, page
range, and block references. Figures are searched as their own path. All
queries run under RLS and are further scoped to the uploading user.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RRF_K = 60
CANDIDATES = 50


async def lexical(session: AsyncSession, user_id: UUID, query: str) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT c.id, ts_rank_cd(c.tsv, q) AS score
            FROM chunks c
            JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id,
                 websearch_to_tsquery('english', :q) q
            WHERE c.tsv @@ q AND s.uploaded_by = :u AND s.deleted_at IS NULL
            ORDER BY score DESC
            LIMIT :n
            """
        ),
        {"q": query, "u": user_id, "n": CANDIDATES},
    )
    return [dict(row) for row in rows.mappings()]


async def dense(
    session: AsyncSession, user_id: UUID, vector: Sequence[float]
) -> list[dict[str, Any]]:
    literal = "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
    rows = await session.execute(
        text(
            """
            SELECT c.id, 1 - (c.embedding <=> CAST(:v AS vector)) AS score
            FROM chunks c
            JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
            WHERE c.embedding IS NOT NULL AND s.uploaded_by = :u AND s.deleted_at IS NULL
            ORDER BY c.embedding <=> CAST(:v AS vector)
            LIMIT :n
            """
        ),
        {"v": literal, "u": user_id, "n": CANDIDATES},
    )
    return [dict(row) for row in rows.mappings()]


def rrf(*rankings: list[dict[str, Any]]) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking):
            scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


async def hydrate(session: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, dict[str, Any]]:
    if not ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT c.id, c.source_id, s.title AS source_title, c.page_from, c.page_to,
                   c.heading, c.text, c.block_refs
            FROM chunks c JOIN sources s ON s.id = c.source_id
            WHERE c.id = ANY(:ids)
            """
        ),
        {"ids": list(ids)},
    )
    return {row["id"]: dict(row) for row in rows.mappings()}


_FIGURE_COLUMNS = (
    "f.id, f.source_id, s.title AS source_title, f.page_no, f.figure_no, "
    "f.caption, f.description, f.modality, f.anatomy, f.image_key"
)
_FIGURE_TSV = (
    "to_tsvector('english', f.caption || ' ' || f.description || ' ' "
    "|| f.modality || ' ' || f.anatomy)"
)


async def search_figures(
    session: AsyncSession,
    user_id: UUID,
    query: str,
    limit: int = 12,
    query_vector: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """Figures by keyword and, when a query vector is given, by meaning (RRF)."""
    lexical_rows = await session.execute(
        text(
            f"SELECT {_FIGURE_COLUMNS}, ts_rank_cd({_FIGURE_TSV}, q) AS score "  # nosec B608 - constant fragments; values are bound
            "FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id, "
            "websearch_to_tsquery('english', :q) q "
            f"WHERE {_FIGURE_TSV} @@ q AND s.uploaded_by = :u AND s.deleted_at IS NULL "
            "ORDER BY score DESC LIMIT :n"
        ),
        {"q": query, "u": user_id, "n": CANDIDATES},
    )
    lexical_hits = [dict(row) for row in lexical_rows.mappings()]
    dense_hits: list[dict[str, Any]] = []
    if query_vector is not None:
        literal = "[" + ",".join(f"{value:.7f}" for value in query_vector) + "]"
        dense_rows = await session.execute(
            text(
                f"SELECT {_FIGURE_COLUMNS}, 1 - (f.embedding <=> CAST(:v AS vector)) AS score "  # nosec B608 - constant fragments; values are bound
                "FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id "
                "WHERE f.embedding IS NOT NULL AND s.uploaded_by = :u AND s.deleted_at IS NULL "
                "ORDER BY f.embedding <=> CAST(:v AS vector) LIMIT :n"
            ),
            {"v": literal, "u": user_id, "n": CANDIDATES},
        )
        dense_hits = [dict(row) for row in dense_rows.mappings()]
    by_id = {row["id"]: row for row in lexical_hits + dense_hits}
    return [{**by_id[fid], "score": round(score, 6)}
            for fid, score in rrf(lexical_hits, dense_hits)[:limit]]


async def hybrid_search(
    session: AsyncSession,
    user_id: UUID,
    query: str,
    query_vector: Sequence[float] | None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    lex = await lexical(session, user_id, query)
    vec = await dense(session, user_id, query_vector) if query_vector is not None else []
    fused = rrf(lex, vec)[:limit]
    details = await hydrate(session, [chunk_id for chunk_id, _ in fused])
    hits = []
    for chunk_id, score in fused:
        row = details.get(chunk_id)
        if row is None:
            continue
        hits.append({**row, "score": round(score, 6),
                     "matched": {"lexical": any(r["id"] == chunk_id for r in lex),
                                 "dense": any(r["id"] == chunk_id for r in vec)}})
    return hits
