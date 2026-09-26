"""Gather a topic's verified claims and graph neighbours for SBA generation (ADR 0029).

Returns None when the topic has too few usable claims or neighbours, so the
caller falls back to chunk-based generation (or refuses when claims were
explicitly asked for).
"""

from __future__ import annotations

from uuid import UUID

from apps.api.app.knowledge import claim_select
from packages.assessment.claim_questions import (
    MAX_CLAIMS,
    MAX_NEIGHBOUR_CLAIMS,
    MAX_NEIGHBOURS,
    Neighbour,
    build_material,
)
from packages.assessment.validation import Excerpt
from sqlalchemy.ext.asyncio import AsyncSession


async def claim_material(
    session: AsyncSession, user_id: UUID, topic: str
) -> tuple[list[Excerpt], list[Neighbour]] | None:
    concepts = await claim_select.topic_concepts(session, user_id, topic)
    if not concepts:
        return None
    claims = await claim_select.concept_claims(session, user_id, concepts, MAX_CLAIMS)
    rows = await claim_select.graph_neighbours(session, user_id, concepts, MAX_NEIGHBOURS)
    neighbour_claims = await claim_select.concept_claims(
        session, user_id, [row["id"] for row in rows], MAX_NEIGHBOUR_CLAIMS * 3)
    return build_material(claims, rows, neighbour_claims)
