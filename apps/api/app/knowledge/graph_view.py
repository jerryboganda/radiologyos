"""1-2 hop concept neighbourhood for the concept-page graph (ADR 0030).

Only edges extracted from the caller's own sources are traversed, merged
concepts are left out, and the result is capped (spec: traversal depth <= 3;
the page asks for at most 2).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_NODES = 40
MAX_EDGES = 120

_NODES = """
WITH RECURSIVE hop(id, depth) AS (
    SELECT CAST(:c AS uuid), 0
    UNION
    SELECT CASE WHEN e.from_concept = h.id THEN e.to_concept ELSE e.from_concept END,
           h.depth + 1
    FROM hop h
    JOIN concept_edges e ON h.id IN (e.from_concept, e.to_concept)
    JOIN sources s ON s.id = e.source_id AND s.uploaded_by = :u AND s.deleted_at IS NULL
    WHERE h.depth < :d
)
SELECT k.id, k.name, k.concept_type, min(h.depth) AS depth
FROM hop h JOIN concepts k ON k.id = h.id
WHERE k.merged_into IS NULL
GROUP BY k.id, k.name, k.concept_type
ORDER BY depth, k.name
LIMIT :n
"""

_EDGES = """
SELECT DISTINCT e.from_concept AS source, e.to_concept AS target, e.relation
FROM concept_edges e
JOIN sources s ON s.id = e.source_id AND s.uploaded_by = :u AND s.deleted_at IS NULL
WHERE e.from_concept = ANY(:ids) AND e.to_concept = ANY(:ids)
ORDER BY e.relation
LIMIT :n
"""


async def neighbourhood(
    session: AsyncSession, user_id: UUID, concept_id: UUID, depth: int
) -> dict[str, Any]:
    nodes = [dict(r) for r in (await session.execute(
        text(_NODES), {"c": concept_id, "u": user_id, "d": depth, "n": MAX_NODES}
    )).mappings()]
    ids = [n["id"] for n in nodes]
    edges = [dict(r) for r in (await session.execute(
        text(_EDGES), {"ids": ids, "u": user_id, "n": MAX_EDGES}
    )).mappings()] if len(ids) > 1 else []
    return {"center": concept_id, "depth": depth, "nodes": nodes, "edges": edges}
