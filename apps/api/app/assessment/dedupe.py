"""Duplicate-checked insertion of generated questions (spec section 8, step 5).

Each checked item is compared with the owner's existing questions before it is
stored, one at a time inside the same transaction, so two near-identical items
in one generated batch also catch each other. With Voyage configured the stem
embedding is compared by cosine similarity (and stored for later checks);
otherwise, or when the embedding call fails, ``pg_trgm`` similarity over
normalised stems is the fallback. Only ids and scores leave this module.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from apps.api.app.assessment import store
from packages.assessment.duplicates import (
    DuplicateHit,
    is_duplicate,
    normalize_stem,
    vector_literal,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Embed = Callable[[Sequence[str]], list[list[float]] | None]


@dataclass(slots=True)
class DedupeOutcome:
    created: list[UUID] = field(default_factory=list)
    duplicates: list[tuple[int, DuplicateHit]] = field(default_factory=list)
    method: str = "trigram"


def embed_stems(stems: Sequence[str]) -> tuple[list[list[float]] | None, str | None]:
    """Stem embeddings from the free local voyage-4-nano service (ADR 0019).

    Returns (None, None) when the local service is unavailable; dedupe then
    falls back to trigram similarity. No paid Voyage call is made here.
    """
    from packages.models.embeddings import LocalEmbedder
    from packages.models.gateway import routing_config

    config = routing_config().embeddings
    if config is None or not stems:
        return None, None
    vectors = LocalEmbedder(config.query, config.dimensions, timeout_s=20.0).embed(
        list(stems), "document")
    return (vectors, config.query.model) if vectors else (None, None)


async def nearest_by_embedding(
    session: AsyncSession, user_id: UUID, vector: Sequence[float]
) -> DuplicateHit | None:
    row = (
        await session.execute(
            text(
                "SELECT id, 1 - (embedding <=> CAST(:v AS vector)) AS sim FROM questions "
                "WHERE user_id = :u AND embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"
            ),
            {"u": user_id, "v": vector_literal(vector)},
        )
    ).first()
    return DuplicateHit(row[0], round(float(row[1]), 4), "embedding") if row else None


async def nearest_by_trigram(
    session: AsyncSession, user_id: UUID, stem: str
) -> DuplicateHit | None:
    row = (
        await session.execute(
            text(
                "SELECT id, similarity(stem_norm, :s) AS sim FROM questions "
                "WHERE user_id = :u AND stem_norm IS NOT NULL ORDER BY sim DESC, id LIMIT 1"
            ),
            {"u": user_id, "s": normalize_stem(stem)},
        )
    ).first()
    return DuplicateHit(row[0], round(float(row[1]), 4), "trigram") if row else None


async def _nearest(
    session: AsyncSession, user_id: UUID, stem: str, vector: Sequence[float] | None
) -> DuplicateHit | None:
    if vector is not None:
        return await nearest_by_embedding(session, user_id, vector)
    return await nearest_by_trigram(session, user_id, stem)


async def insert_unique(
    session: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    rows: Sequence[tuple[int, dict[str, Any]]],
    vectors: list[list[float]] | None,
    embed_model: str | None,
) -> DedupeOutcome:
    """Insert (index, row) pairs that are not near-duplicates of the owner's bank."""
    outcome = DedupeOutcome(method="embedding" if vectors is not None else "trigram")
    for position, (index, values) in enumerate(rows):
        vector = vectors[position] if vectors is not None else None
        hit = await _nearest(session, user_id, values["stem"], vector)
        if hit is not None and is_duplicate(hit.similarity, hit.method):
            outcome.duplicates.append((index, hit))
            continue
        extra = {"embedding": vector_literal(vector), "embed_model": embed_model} if vector else {}
        outcome.created.append(
            await store.insert_question(session, tenant_id, user_id, {**values, **extra}))
    return outcome
