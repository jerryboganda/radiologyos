"""Read the caller's usable claims, figures, and graph neighbours (ADR 0029).

Concepts, claims, and edges are tenant-scoped (RLS); a claim or edge is used only
when its source is the caller's own, non-deleted upload. A usable claim is
``active``: its evidence span was verified verbatim at extraction and it is not
disputed, superseded, or rejected. Claims a second source agrees with
(``verification = 'verified'``) are preferred. Nothing here copies source text
into new tables; callers build cards and prompts from what is read.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from packages.knowledge.text import normalize_name
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
LIVE = "s.uploaded_by = :u AND s.deleted_at IS NULL"
CLAIM_SELECT = f"""
    SELECT cl.id, cl.concept_id, c.name AS concept_name, c.aliases,
           c.curriculum_code AS concept_code, cl.statement, cl.evidence_span, cl.source_id,
           s.title AS source_title, cl.chunk_id, cl.page_from, cl.page_to, cl.citation,
           cl.verification, cl.importance,
           (SELECT m.curriculum_code FROM curriculum_mappings m
             WHERE m.chunk_id = cl.chunk_id AND m.status = 'accepted'
             ORDER BY m.confidence DESC LIMIT 1) AS mapped_code
    FROM claims cl
    JOIN concepts c ON c.id = cl.concept_id AND c.tenant_id = cl.tenant_id
    JOIN sources s ON s.id = cl.source_id AND s.tenant_id = cl.tenant_id
    WHERE {LIVE} AND cl.status = 'active'
"""  # nosec B608 - constant SQL; the only interpolation is the constant LIVE predicate
CLAIM_ORDER = " ORDER BY (cl.verification = 'verified') DESC, cl.importance DESC, cl.id"
FIGURE_SELECT = f"""
    SELECT f.id, f.source_id, s.title AS source_title, f.page_no, f.caption, f.description,
           f.modality, f.anatomy, f.findings, f.bbox,
           (SELECT m.curriculum_code FROM curriculum_mappings m
             WHERE m.source_id = f.source_id AND m.status = 'accepted'
               AND f.page_no BETWEEN m.page_from AND m.page_to
             ORDER BY m.confidence DESC LIMIT 1) AS mapped_code
    FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id
    WHERE {LIVE} AND btrim(f.description) <> ''
"""  # nosec B608 - constant SQL; the only interpolation is the constant LIVE predicate
_NEIGHBOURS = f"""
    WITH target AS (SELECT unnest(CAST(:ids AS uuid[])) AS id),
    edges AS (
        SELECT e.* FROM concept_edges e
        JOIN sources s ON s.id = e.source_id AND s.tenant_id = e.tenant_id WHERE {LIVE}),
    direct AS (
        SELECT CASE WHEN e.from_concept = t.id THEN e.to_concept ELSE e.from_concept END AS id,
               e.relation, 1 AS rank, t.id AS of_concept
        FROM edges e JOIN target t ON t.id IN (e.from_concept, e.to_concept)
        WHERE e.relation IN ('differential_of', 'contrasts_with')),
    sibling AS (
        SELECT b.from_concept AS id, 'sibling' AS relation, 2 AS rank, t.id AS of_concept
        FROM target t
        JOIN edges a ON a.from_concept = t.id AND a.relation IN ('is_a', 'part_of', 'classified_by')
        JOIN edges b ON b.to_concept = a.to_concept AND b.relation = a.relation
                    AND b.from_concept <> t.id)
    SELECT DISTINCT ON (n.id) n.id, c.name, c.aliases, n.relation, n.rank, n.of_concept
    FROM (SELECT * FROM direct UNION ALL SELECT * FROM sibling) n
    JOIN concepts c ON c.id = n.id
    WHERE NOT (n.id = ANY(CAST(:ids AS uuid[])))
    ORDER BY n.id, n.rank
"""  # nosec B608 - constant SQL; the only interpolation is the constant LIVE predicate


async def _rows(session: AsyncSession, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await session.execute(text(sql), params)
    return [dict(row) for row in result.mappings()]


def _like(topic: str) -> str:
    escaped = topic.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def topic_concepts(
    session: AsyncSession, user_id: UUID, topic: str, limit: int = 6
) -> list[UUID]:
    """Concepts named by (or close to) ``topic``, or under a curriculum code, with usable claims."""
    key = normalize_name(topic)
    code = topic.strip().upper() if _CODE.match(topic.strip().upper()) else None
    rows = await _rows(session, f"""
        SELECT c.id FROM concepts c
        WHERE (c.normalized_name = :k OR :k = ANY(c.alias_keys)
               OR c.curriculum_code = CAST(:code AS text)
               OR c.curriculum_code LIKE CAST(:code AS text) || '.%'
               OR similarity(c.normalized_name, :k) >= 0.45)
          AND EXISTS (SELECT 1 FROM claims cl
                      JOIN sources s ON s.id = cl.source_id AND s.tenant_id = cl.tenant_id
                      WHERE cl.concept_id = c.id AND cl.status = 'active' AND {LIVE})
        ORDER BY (c.normalized_name = :k OR :k = ANY(c.alias_keys)) DESC,
                 similarity(c.normalized_name, :k) DESC, c.id
        LIMIT :n
        """, {"k": key, "code": code, "u": user_id, "n": limit})  # nosec B608 - constant SQL fragments; values are bound
    return [row["id"] for row in rows]


async def concept_claims(
    session: AsyncSession, user_id: UUID, concept_ids: Sequence[UUID], limit: int
) -> list[dict[str, Any]]:
    if not concept_ids:
        return []
    return await _rows(
        session, CLAIM_SELECT + " AND cl.concept_id = ANY(CAST(:ids AS uuid[]))" + CLAIM_ORDER
        + " LIMIT :n", {"u": user_id, "ids": list(concept_ids), "n": limit})


async def graph_neighbours(
    session: AsyncSession, user_id: UUID, concept_ids: Sequence[UUID], limit: int
) -> list[dict[str, Any]]:
    """Differentials and contrasts first, then siblings under a shared parent."""
    if not concept_ids:
        return []
    rows = await _rows(session, _NEIGHBOURS, {"u": user_id, "ids": list(concept_ids)})
    rows.sort(key=lambda row: (row["rank"], str(row["name"]).casefold()))
    return rows[:limit]


async def cloze_candidates(
    session: AsyncSession, user_id: UUID, source_id: UUID | None, topic: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Usable claims the caller has no cloze card for, optionally by source or topic."""
    sql, params = CLAIM_SELECT + (  # nosec B608 - constant fragments; values are bound
        " AND NOT EXISTS (SELECT 1 FROM cards k WHERE k.claim_id = cl.id AND k.user_id = :u)"
    ), {"u": user_id, "n": limit}
    if source_id is not None:
        sql, params["s"] = sql + " AND cl.source_id = :s", source_id
    if topic:
        ids = await topic_concepts(session, user_id, topic, limit=12)
        if not ids:
            return []
        sql, params["ids"] = sql + " AND cl.concept_id = ANY(CAST(:ids AS uuid[]))", ids
    return await _rows(session, sql + CLAIM_ORDER + " LIMIT :n", params)


async def figure_candidates(
    session: AsyncSession, user_id: UUID, source_id: UUID | None, topic: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Described figures the caller has no image card for, optionally by source or topic."""
    sql, params = FIGURE_SELECT + (  # nosec B608 - constant fragments; values are bound
        " AND NOT EXISTS (SELECT 1 FROM cards k WHERE k.figure_id = f.id AND k.user_id = :u)"
    ), {"u": user_id, "n": limit}
    if source_id is not None:
        sql, params["s"] = sql + " AND f.source_id = :s", source_id
    if topic:
        sql, params["like"] = sql + (
            " AND (f.caption ILIKE :like OR f.description ILIKE :like "
            "OR f.anatomy ILIKE :like)"), _like(topic.strip())
    return await _rows(session, sql + " ORDER BY f.source_id, f.page_no, f.figure_no LIMIT :n",
                       params)
