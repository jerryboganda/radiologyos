"""Knowledge graph reads and conflict resolution (tenant session, RLS).

Claims are visible only when their source belongs to the caller (personal
uploads are never shown to another member of the same tenant); a concept is
listed only when it has at least one such claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.knowledge.text import normalize_name
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_VISIBLE = (
    "EXISTS (SELECT 1 FROM claims c JOIN sources s ON s.id = c.source_id "
    "WHERE c.concept_id = k.id AND s.uploaded_by = :u AND s.deleted_at IS NULL)"
)


async def search_concepts(
    session: AsyncSession, user_id: UUID, query: str | None, limit: int
) -> list[dict[str, Any]]:
    key = normalize_name(query or "")
    rows = await session.execute(
        text(
            f"""
            SELECT k.id, k.name, k.aliases, k.concept_type, k.curriculum_code,
                   (SELECT count(*) FROM claims c WHERE c.concept_id = k.id) AS claim_count,
                   (SELECT count(*) FROM knowledge_conflicts x WHERE x.concept_id = k.id
                      AND x.status = 'open') AS open_conflicts
            FROM concepts k
            WHERE {_VISIBLE}
              AND (:key = '' OR strpos(k.normalized_name, :key) > 0
                   OR :key = ANY(k.alias_keys) OR similarity(k.normalized_name, :key) >= 0.4)
            ORDER BY CASE WHEN :key = '' THEN 0 ELSE similarity(k.normalized_name, :key) END DESC,
                     k.name
            LIMIT :limit
            """  # nosec B608 - constant column list; all values are bound parameters
        ),
        {"u": user_id, "key": key, "limit": limit},
    )
    return [dict(row) for row in rows.mappings()]


async def concept_detail(
    session: AsyncSession, user_id: UUID, concept_id: UUID
) -> dict[str, Any] | None:
    concept = (
        await session.execute(
            text(
                f"SELECT k.id, k.name, k.aliases, k.concept_type, k.curriculum_code, "  # nosec B608 - constant column list; all values are bound parameters
                f"k.curriculum_confidence, k.summary FROM concepts k "
                f"WHERE k.id = :id AND {_VISIBLE}"
            ),
            {"id": concept_id, "u": user_id},
        )
    ).mappings().first()
    if concept is None:
        return None
    claims = await session.execute(
        text(
            """
            SELECT c.id, c.claim_type, c.statement, c.evidence_span, c.status, c.verification,
                   c.importance, c.modality, c.citation, c.supporting, c.agent_version
            FROM claims c JOIN sources s ON s.id = c.source_id
            WHERE c.concept_id = :id AND s.uploaded_by = :u AND s.deleted_at IS NULL
            ORDER BY c.importance DESC, c.created_at
            """
        ),
        {"id": concept_id, "u": user_id},
    )
    edges = await session.execute(
        text(
            """
            SELECT e.id, e.relation, e.citation,
                   CASE WHEN e.from_concept = :id THEN 'out' ELSE 'in' END AS direction,
                   o.id AS other_id, o.name AS other_name
            FROM concept_edges e
            JOIN concepts o ON o.id = CASE WHEN e.from_concept = :id
                                            THEN e.to_concept ELSE e.from_concept END
            WHERE e.from_concept = :id OR e.to_concept = :id
            ORDER BY e.relation, o.name
            """
        ),
        {"id": concept_id},
    )
    conflicts = await list_conflicts(session, user_id, None, concept_id)
    return {**dict(concept), "claims": [dict(r) for r in claims.mappings()],
            "edges": [dict(r) for r in edges.mappings()], "conflicts": conflicts}


async def list_conflicts(
    session: AsyncSession, user_id: UUID, status: str | None, concept_id: UUID | None = None
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT x.id, x.concept_id, k.name AS concept_name, x.kind, x.description, x.status,
                   x.resolution, x.preferred_claim, x.resolved_at, x.created_at,
                   a.id AS a_id, a.statement AS a_statement, a.evidence_span AS a_span,
                   a.citation AS a_citation,
                   b.id AS b_id, b.statement AS b_statement, b.evidence_span AS b_span,
                   b.citation AS b_citation
            FROM knowledge_conflicts x
            JOIN concepts k ON k.id = x.concept_id
            JOIN claims a ON a.id = x.claim_a
            JOIN claims b ON b.id = x.claim_b
            JOIN sources sa ON sa.id = a.source_id
            WHERE sa.uploaded_by = :u
              AND (CAST(:status AS text) IS NULL OR x.status = :status)
              AND (CAST(:concept AS uuid) IS NULL OR x.concept_id = :concept)
            ORDER BY x.status, x.created_at DESC
            LIMIT 200
            """
        ),
        {"u": user_id, "status": status, "concept": concept_id},
    )
    return [dict(row) for row in rows.mappings()]


async def resolve_conflict(
    session: AsyncSession, principal: Principal, conflict_id: UUID, resolution: str,
    preferred_claim: UUID | None,
) -> dict[str, Any] | None:
    """Close a conflict; the preferred claim becomes active, the other superseded."""
    found = [c for c in await list_conflicts(session, principal.user_id, None)
             if c["id"] == conflict_id]
    if not found:
        return None
    conflict = found[0]
    pair = (conflict["a_id"], conflict["b_id"])
    if preferred_claim is not None and preferred_claim not in pair:
        raise ValueError("preferred claim is not part of this conflict")
    await session.execute(
        text(
            "UPDATE knowledge_conflicts SET status = 'resolved', resolution = :r, "
            "preferred_claim = :p, resolved_by = :u, resolved_at = now() WHERE id = :id"
        ),
        {"r": resolution, "p": preferred_claim, "u": principal.user_id, "id": conflict_id},
    )
    for claim_id in pair:
        status = "active"
        if preferred_claim is not None and claim_id != preferred_claim:
            status = "superseded"
        await session.execute(
            text(
                "UPDATE claims SET status = :s WHERE id = :id AND NOT EXISTS ("
                "SELECT 1 FROM knowledge_conflicts x WHERE x.status = 'open' "
                "AND :id IN (x.claim_a, x.claim_b))"
            ),
            {"s": status, "id": claim_id},
        )
    await audit(session, principal, "knowledge.conflict_resolved", "knowledge_conflict",
                str(conflict_id), {"preferred_claim": str(preferred_claim or "")})
    await session.commit()
    return {**conflict, "status": "resolved", "resolution": resolution,
            "preferred_claim": preferred_claim, "resolved_at": datetime.now(UTC)}
