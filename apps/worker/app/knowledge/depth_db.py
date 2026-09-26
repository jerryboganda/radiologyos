"""Reads for the knowledge-depth pass (tenant session, RLS; ADR 0030).

Claims are always read for one owner (``sources.uploaded_by``), so a note or a
resolver prompt never mixes in another member's personal uploads.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.knowledge.text import CANDIDATE
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CONCEPT_COLUMNS = (
    "k.id, k.name, k.normalized_name, k.concept_type, k.aliases, k.alias_keys, "
    "k.curriculum_code, k.merged_into, k.created_at, "
    "(SELECT count(*) FROM claims c WHERE c.concept_id = k.id) AS claim_count"
)


async def concept(session: AsyncSession, concept_id: UUID) -> dict[str, Any] | None:
    row = (await session.execute(
        text(f"SELECT {_CONCEPT_COLUMNS} FROM concepts k WHERE k.id = :id"),  # nosec B608 - constant column list
        {"id": concept_id},
    )).mappings().first()
    return dict(row) if row else None


async def touched_concepts(session: AsyncSession, source_id: UUID) -> list[UUID]:
    """Live (unmerged) concepts that carry at least one claim of this source."""
    rows = await session.execute(
        text(
            "SELECT DISTINCT coalesce(k.merged_into, k.id) AS id FROM claims c "
            "JOIN concepts k ON k.id = c.concept_id WHERE c.source_id = :s ORDER BY 1"
        ),
        {"s": source_id},
    )
    values: list[Any] = list(rows.scalars())
    return [UUID(str(r)) for r in values]


async def owner_claims(
    session: AsyncSession, user_id: UUID, concept_id: UUID, limit: int = 200
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT c.id, c.claim_type, c.statement, c.evidence_span, c.status, c.importance,
                   c.modality, c.citation
            FROM claims c JOIN sources s ON s.id = c.source_id
            WHERE c.concept_id = :c AND s.uploaded_by = :u AND s.deleted_at IS NULL
              AND c.status IN ('active', 'disputed')
            ORDER BY c.importance DESC, c.id
            LIMIT :n
            """
        ),
        {"c": concept_id, "u": user_id, "n": limit},
    )
    return [dict(r) for r in rows.mappings()]


async def differentials(session: AsyncSession, concept_id: UUID) -> list[dict[str, Any]]:
    """Concepts linked by a ``differential_of`` edge in either direction."""
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT o.id, o.name, o.normalized_name FROM concept_edges e
            JOIN concepts o ON o.id = CASE WHEN e.from_concept = :c
                                           THEN e.to_concept ELSE e.from_concept END
            WHERE (e.from_concept = :c OR e.to_concept = :c) AND e.relation = 'differential_of'
              AND o.merged_into IS NULL
            ORDER BY o.name LIMIT 20
            """
        ),
        {"c": concept_id},
    )
    return [dict(r) for r in rows.mappings()]


async def near_concepts(session: AsyncSession, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Unmerged concepts whose name is trigram-similar (>= 0.80) to this one."""
    rows = await session.execute(
        text(
            f"""
            SELECT {_CONCEPT_COLUMNS} FROM concepts k
            WHERE k.id <> :id AND k.merged_into IS NULL
              AND similarity(k.normalized_name, :key) >= :floor
            ORDER BY similarity(k.normalized_name, :key) DESC LIMIT 5
            """  # nosec B608 - constant column list; values are bound
        ),
        {"id": row["id"], "key": row["normalized_name"], "floor": CANDIDATE},
    )
    return [dict(r) for r in rows.mappings()]


async def pair_decided(session: AsyncSession, a: UUID, b: UUID) -> bool:
    found = (await session.execute(
        text("SELECT 1 FROM concept_merges WHERE concept_a = :a AND concept_b = :b"),
        {"a": a, "b": b},
    )).first()
    return found is not None


async def unclassified_conflicts(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT x.id, x.kind, x.description, k.name AS concept_name,
                   x.claim_a AS a_id, x.claim_b AS b_id,
                   a.statement AS a_statement, a.evidence_span AS a_span,
                   a.citation AS a_citation,
                   b.statement AS b_statement, b.evidence_span AS b_span,
                   b.citation AS b_citation
            FROM knowledge_conflicts x
            JOIN concepts k ON k.id = x.concept_id
            JOIN claims a ON a.id = x.claim_a
            JOIN claims b ON b.id = x.claim_b
            WHERE x.status = 'open' AND x.ai_label IS NULL
              AND (a.source_id = :s OR b.source_id = :s)
            ORDER BY x.created_at, x.id
            """
        ),
        {"s": source_id},
    )
    return [dict(r) for r in rows.mappings()]
