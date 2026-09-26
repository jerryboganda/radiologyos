"""Knowledge-graph expansion queries for the tutor (ADR 0028).

Three bounded reads under RLS, each also scoped to the caller's own,
non-deleted sources: the seed concepts of the top retrieved chunks (via the
claims extracted from them), their 1-hop ``concept_edges``, and the active
claims of seeds and neighbours with their evidence references. Selection and
labelling are pure (``packages.tutor.graph``). Nothing is logged here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from packages.tutor.graph import budget_for, pick_neighbours, select_claims
from packages.tutor.grounding import Excerpt
from packages.tutor.intent import Intent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _seeds(
    session: AsyncSession, user_id: UUID, chunk_ids: Sequence[UUID], limit: int
) -> list[tuple[UUID, str]]:
    rows = await session.execute(
        text(
            "SELECT co.id, co.name, min(array_position(CAST(:ids AS uuid[]), cl.chunk_id)) AS r "
            "FROM claims cl JOIN concepts co ON co.id = cl.concept_id "
            "JOIN sources s ON s.id = cl.source_id AND s.tenant_id = cl.tenant_id "
            "AND s.uploaded_by = :u AND s.deleted_at IS NULL "
            "WHERE cl.chunk_id = ANY(CAST(:ids AS uuid[])) AND cl.status = 'active' "
            "GROUP BY co.id, co.name ORDER BY r, co.name LIMIT :n"
        ),
        {"ids": list(chunk_ids), "u": user_id, "n": limit},
    )
    return [(row["id"], str(row["name"])) for row in rows.mappings()]


async def _edges(
    session: AsyncSession, user_id: UUID, seeds: Sequence[UUID], limit: int
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT e.from_concept, e.to_concept, e.relation FROM concept_edges e "
            "JOIN sources s ON s.id = e.source_id AND s.tenant_id = e.tenant_id "
            "AND s.uploaded_by = :u AND s.deleted_at IS NULL "
            "WHERE e.from_concept = ANY(CAST(:ids AS uuid[])) "
            "OR e.to_concept = ANY(CAST(:ids AS uuid[])) "
            "ORDER BY e.created_at LIMIT :n"
        ),
        {"ids": list(seeds), "u": user_id, "n": limit},
    )
    return [dict(row) for row in rows.mappings()]


async def _claims(
    session: AsyncSession, user_id: UUID, concepts: Sequence[UUID], per_concept: int
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT * FROM (SELECT cl.id, cl.concept_id, co.name AS concept_name, "
            "cl.evidence_span, cl.source_id, s.title AS source_title, cl.chunk_id, "
            "cl.page_from, cl.page_to, cl.citation, cl.verification, cl.importance, "
            "row_number() OVER (PARTITION BY cl.concept_id ORDER BY "
            "(cl.verification = 'verified') DESC, cl.importance DESC, cl.created_at) AS rn "
            "FROM claims cl JOIN concepts co ON co.id = cl.concept_id "
            "JOIN sources s ON s.id = cl.source_id AND s.tenant_id = cl.tenant_id "
            "AND s.uploaded_by = :u AND s.deleted_at IS NULL "
            "WHERE cl.concept_id = ANY(CAST(:ids AS uuid[])) AND cl.status = 'active' "
            "AND cl.chunk_id IS NOT NULL) ranked WHERE rn <= :n"
        ),
        {"ids": list(concepts), "u": user_id, "n": per_concept},
    )
    return [dict(row) for row in rows.mappings()]


async def expand(
    session: AsyncSession, user_id: UUID, chunk_ids: Sequence[UUID], intent: Intent,
) -> list[Excerpt]:
    """K-labelled claim excerpts for the top chunks' concepts and their neighbours."""
    budget = budget_for(intent)
    top = list(chunk_ids)[: budget.seed_chunks]
    if not top or budget.claims == 0:
        return []
    seeds = await _seeds(session, user_id, top, budget.seed_concepts)
    if not seeds:
        return []
    seed_ids = [cid for cid, _ in seeds]
    edges = await _edges(session, user_id, seed_ids, budget.neighbours * 8)
    neighbours = pick_neighbours(edges, seed_ids, intent, budget.neighbours)
    concepts = [*seed_ids, *(n.concept_id for n in neighbours)]
    rows = await _claims(session, user_id, concepts, budget.per_concept * 3)
    return select_claims(rows, seed_ids, neighbours, budget, set(chunk_ids), dict(seeds))
