"""Metered Voyage reranking after RRF fusion (ADR 0028).

``rerank_hits`` reorders fused hits by relevance to the query, keeps at most
``limit``, and drops any below ``min_score``. Like query embedding (ADR 0019),
every call first checks the model's own lifetime ledger
(``app.voyage_model_tokens_total``) against its hard cap, records its tokens
afterwards, and raises amber/red ``rerank_budget`` alerts. It **fails open**:
past the cap, without a key, or on any error it returns the hits in their RRF
order and never raises into a request. Only counts and outcomes are logged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.api.app.db.session import engine, tenant_session
from apps.api.app.library import search
from apps.api.app.observability import logger
from apps.worker.app.ingest.budget_alerts import AlertKind, record_alert
from apps.worker.app.ingest.embedding import add_usage
from fastapi.concurrency import run_in_threadpool
from packages.models.budget import BudgetState, EmbeddingBudgetExhausted, crossed
from packages.models.rerank import RerankError, RerankResult, VoyageReranker, estimate_tokens
from packages.models.routing import RerankConfig
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

KIND: AlertKind = "rerank_budget"
_FAIL_OPEN = (RerankError, EmbeddingBudgetExhausted, SQLAlchemyError, OSError, ValueError)


@dataclass(frozen=True, slots=True)
class Reranked:
    hits: list[dict[str, Any]]
    reranked: bool


def config() -> RerankConfig | None:
    from packages.models.gateway import routing_config

    return routing_config().rerank


def ready() -> VoyageReranker | None:
    """The configured reranker when it can be called (a key is present), else None."""
    cfg = config()
    if cfg is None:
        return None
    reranker = VoyageReranker(cfg)
    return reranker if reranker.available() else None


def candidate_pool(limit: int) -> int:
    """How many fused hits to fetch: the rerank pool when it will run, else ``limit``."""
    reranker = ready()
    return max(limit, reranker.config.candidates) if reranker is not None else limit


def document_text(hit: dict[str, Any]) -> str:
    heading = str(hit.get("heading") or "").strip()
    body = str(hit.get("text") or "")
    return f"{heading}\n{body}" if heading and not body.startswith(heading) else body


async def rerank_hits(
    tenant_id: UUID, query: str, hits: Sequence[dict[str, Any]], limit: int
) -> Reranked:
    """Hits reordered by the reranker, or the first ``limit`` in RRF order (fail-open)."""
    fused = Reranked([dict(h) for h in hits[:limit]], False)
    reranker = ready()
    if reranker is None or len(hits) < 2 or not query.strip():
        return fused
    try:
        result = await _metered(reranker, tenant_id, query, [document_text(h) for h in hits],
                                limit)
    except _FAIL_OPEN as exc:
        logger.warning("rerank_skipped", extra={"error_type": type(exc).__name__,
                                                "candidates": len(hits)})
        return fused
    floor = reranker.config.min_score
    kept = [{**hits[r.index], "score": round(r.score, 6)}
            for r in result.ranking if r.score >= floor][:limit]
    logger.info("reranked", extra={"candidates": len(hits), "kept": len(kept),
                                   "tokens": result.tokens})
    return Reranked(kept, True)


async def _metered(
    reranker: VoyageReranker, tenant_id: UUID, query: str, documents: list[str], limit: int
) -> RerankResult:
    cfg = reranker.config
    estimate = estimate_tokens(query, documents)
    async with tenant_session(tenant_id) as session:
        used = await model_tokens(session, cfg.model)
    try:
        BudgetState(used, cfg.budget).check(estimate)
    except EmbeddingBudgetExhausted:
        await record_alert(engine, tenant_id, "red", used, cfg.budget, KIND)
        raise
    result = await run_in_threadpool(reranker.rerank, query, documents, limit)
    tokens = result.tokens or estimate
    async with tenant_session(tenant_id) as session:
        await add_usage(session, tenant_id, cfg.model, tokens)
        await session.commit()
    for level in crossed(used, used + tokens, cfg.budget):
        await record_alert(engine, tenant_id, level, used + tokens, cfg.budget, KIND)
    return result


async def model_tokens(session: AsyncSession, model: str) -> int:
    """Lifetime tokens of one Voyage model across tenants (a single number)."""
    total = await session.execute(text("SELECT app.voyage_model_tokens_total(:m)"),
                                  {"m": model})
    return int(total.scalar_one())


async def ranked_search(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, query: str,
    vector: Sequence[float] | None, limit: int, rerank_query: str | None = None,
) -> Reranked:
    """Hybrid (RRF) search over a candidate pool, then metered reranking.

    ``rerank_query`` is the natural-language text for the reranker when
    ``query`` is a keyword expression (the tutor ORs its terms).
    """
    hits = await search.hybrid_search(session, user_id, query, vector, candidate_pool(limit))
    return await rerank_hits(tenant_id, rerank_query or query, hits, limit)
