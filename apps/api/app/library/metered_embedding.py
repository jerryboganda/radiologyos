"""Metered query-time embeddings (ADR 0019, owner override 2026-09-26).

The owner chose the paid best model (voyage-4-large) for everything, inside the
free quota. Every call here checks the lifetime ledger against the 195M hard cap
first, records its tokens afterwards, and raises the same amber/red admin
alerts as document embedding. Past the cap, or on any failure, it returns None
and search falls back to keyword-only; it never raises into a request.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from apps.api.app.db.session import engine, tenant_session
from apps.worker.app.ingest.budget_alerts import record_alert
from apps.worker.app.ingest.embedding import add_usage
from fastapi.concurrency import run_in_threadpool
from packages.models.budget import BudgetState, EmbeddingBudgetExhausted, crossed
from packages.models.embeddings import (
    EmbeddingError,
    InputType,
    LocalEmbedder,
    VoyageEmbedder,
    estimate_tokens,
)
from sqlalchemy import text


async def embed_metered(
    tenant_id: UUID, texts: Sequence[str], input_type: InputType
) -> list[list[float]] | None:
    from packages.models.gateway import routing_config

    config = routing_config().embeddings
    if config is None or not texts:
        return None
    target = config.query
    if target.backend == "local":  # kept for later; currently switched off
        return await run_in_threadpool(
            LocalEmbedder(target, config.dimensions).embed, list(texts), input_type)
    embedder = VoyageEmbedder(target, config.dimensions, timeout_s=15.0, max_attempts=2)
    if not embedder.available():
        return None
    estimate = sum(estimate_tokens(t) for t in texts)
    async with tenant_session(tenant_id) as session:
        total = await session.execute(text("SELECT app.embedding_tokens_total()"))
        used = int(total.scalar_one())
    try:
        BudgetState(used, config.budget).check(estimate)
    except EmbeddingBudgetExhausted:
        await record_alert(engine, tenant_id, "red", used, config.budget)
        return None
    try:
        result = await run_in_threadpool(embedder.embed_batch, list(texts), input_type)
    except EmbeddingError:
        return None
    tokens = result.tokens or estimate
    async with tenant_session(tenant_id) as session:
        await add_usage(session, tenant_id, embedder.model, tokens)
        await session.commit()
    for level in crossed(used, used + tokens, config.budget):
        await record_alert(engine, tenant_id, level, used + tokens, config.budget)
    return result.vectors
