"""Pay-once document embedding with a hard budget stop (ADR 0019).

For one source: hash the normalised text of every chunk and figure that has no
vector, fill what the tenant's ``embedding_cache`` already knows, and send only
the remaining unique texts to Voyage in token-bounded batches. Before every
request the lifetime ledger is checked against the 195M-token cap; after every
request the vectors, cache rows, and ledger are committed together, so a crash
never loses paid work and a re-run never pays twice. Logs carry counts only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.worker.app.ingest.budget_alerts import record_alert
from apps.worker.app.ingest.db import tenant_tx
from packages.models.budget import BudgetState, EmbeddingBudgetExhausted, crossed
from packages.models.embeddings import (
    VoyageEmbedder,
    content_hash,
    embed_text,
    estimate_tokens,
    plan_batches,
)
from packages.models.routing import EmbeddingBudget
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

log = logging.getLogger("radbrain.embedding")
MIN_FIGURE_CHARS = 20


@dataclass(slots=True)
class Pending:
    table: str  # "chunks" | "figures"
    row_id: UUID
    text: str
    sha: str


async def embed_pending(
    engine: AsyncEngine, embedder: VoyageEmbedder, budget: EmbeddingBudget,
    tenant_id: UUID, source_id: UUID,
) -> str:
    async with tenant_tx(engine, tenant_id) as session:
        items = await _pending(session, source_id)
        await _store_hashes(session, items)
        await _fill_from_cache(session, source_id, embedder)
        misses = await _misses(session, items, embedder)
    paid_tokens = 0
    texts = list(misses.values())
    shas = list(misses.keys())
    for batch in plan_batches(texts):
        batch_texts = [texts[i] for i in batch]
        paid_tokens += await _pay_batch(
            engine, embedder, budget, tenant_id, source_id,
            [shas[i] for i in batch], batch_texts,
        )
    log.info("embedded source=%s items=%s paid_texts=%s tokens=%s",
             source_id, len(items), len(texts), paid_tokens)
    return f"items:{len(items)},paid:{len(texts)},tokens:{paid_tokens}"


async def _pay_batch(
    engine: AsyncEngine, embedder: VoyageEmbedder, budget: EmbeddingBudget,
    tenant_id: UUID, source_id: UUID, shas: list[str], texts: list[str],
) -> int:
    estimate = sum(estimate_tokens(t) for t in texts)
    async with tenant_tx(engine, tenant_id) as session:
        total = await session.execute(text("SELECT app.embedding_tokens_total()"))
        used = int(total.scalar_one())
    state = BudgetState(used, budget)
    try:
        state.check(estimate)
    except EmbeddingBudgetExhausted:
        await record_alert(engine, tenant_id, "red", used, budget)
        raise
    result = await asyncio.to_thread(embedder.embed_batch, texts, "document")
    tokens = result.tokens or estimate
    async with tenant_tx(engine, tenant_id) as session:
        await _save_cache(session, tenant_id, embedder, shas, result.vectors)
        await _add_usage(session, tenant_id, embedder.model, tokens)
        await _fill_from_cache(session, source_id, embedder)
    for level in crossed(used, used + tokens, budget):
        await record_alert(engine, tenant_id, level, used + tokens, budget)
    return tokens


async def _pending(session: AsyncSession, source_id: UUID) -> list[Pending]:
    chunks = await session.execute(
        text("SELECT id, heading, text FROM chunks WHERE source_id = :s "
             "AND embedding IS NULL ORDER BY chunk_no"),
        {"s": source_id},
    )
    items = [_item("chunks", r["id"], embed_text(r["heading"], r["text"]))
             for r in chunks.mappings()]
    figures = await session.execute(
        text("SELECT id, caption, modality, anatomy, description, findings FROM figures "
             "WHERE source_id = :s AND embedding IS NULL ORDER BY page_no, figure_no"),
        {"s": source_id},
    )
    for row in figures.mappings():
        body = figure_text(row)
        if len(body) >= MIN_FIGURE_CHARS:
            items.append(_item("figures", row["id"], body))
    return [item for item in items if item.text]


def figure_text(row: Any) -> str:
    findings = row["findings"] or []
    parts = [row["caption"], row["modality"], row["anatomy"], row["description"],
             "; ".join(str(f) for f in findings)]
    return embed_text("", "\n".join(p for p in parts if p))


def _item(table: str, row_id: UUID, body: str) -> Pending:
    return Pending(table, row_id, body, content_hash(body))


async def _store_hashes(session: AsyncSession, items: list[Pending]) -> None:
    for table in ("chunks", "figures"):
        rows = [{"id": i.row_id, "h": i.sha} for i in items if i.table == table]
        if rows:
            await session.execute(
                text(f"UPDATE {table} SET content_sha256 = :h WHERE id = :id"),  # nosec B608 - constant table name
                rows,
            )


async def _misses(
    session: AsyncSession, items: list[Pending], embedder: VoyageEmbedder
) -> dict[str, str]:
    wanted = {i.sha: i.text for i in items}
    if not wanted:
        return {}
    have = await session.execute(
        text("SELECT content_sha256 FROM embedding_cache WHERE content_sha256 = ANY(:h) "
             "AND model = :m AND dimensions = :d"),
        {"h": list(wanted), "m": embedder.model, "d": embedder.dimensions},
    )
    for (sha,) in have.all():
        wanted.pop(str(sha).strip(), None)
    return wanted


async def _fill_from_cache(
    session: AsyncSession, source_id: UUID, embedder: VoyageEmbedder
) -> None:
    for table in ("chunks", "figures"):
        await session.execute(
            text(
                f"UPDATE {table} t SET embedding = e.embedding, embed_model = e.model "  # nosec B608 - constant table name; values are bound
                "FROM embedding_cache e WHERE t.source_id = :s AND t.embedding IS NULL "
                "AND e.tenant_id = t.tenant_id AND e.content_sha256 = t.content_sha256 "
                "AND e.model = :m AND e.dimensions = :d"
            ),
            {"s": source_id, "m": embedder.model, "d": embedder.dimensions},
        )


async def _save_cache(
    session: AsyncSession, tenant_id: UUID, embedder: VoyageEmbedder,
    shas: list[str], vectors: list[list[float]],
) -> None:
    rows = [
        {"t": tenant_id, "h": sha, "m": embedder.model, "d": embedder.dimensions,
         "v": "[" + ",".join(f"{x:.7f}" for x in vector) + "]"}
        for sha, vector in zip(shas, vectors, strict=True)
    ]
    await session.execute(
        text("INSERT INTO embedding_cache (tenant_id, content_sha256, model, dimensions, "
             "embedding) VALUES (:t, :h, :m, :d, CAST(:v AS vector)) ON CONFLICT DO NOTHING"),
        rows,
    )


async def _add_usage(session: AsyncSession, tenant_id: UUID, model: str, tokens: int) -> None:
    await session.execute(
        text(
            "INSERT INTO embedding_usage (tenant_id, day, model, tokens, requests) "
            "VALUES (:t, CURRENT_DATE, :m, :n, 1) ON CONFLICT (tenant_id, day, model) "
            "DO UPDATE SET tokens = embedding_usage.tokens + EXCLUDED.tokens, "
            "requests = embedding_usage.requests + 1"
        ),
        {"t": tenant_id, "m": model, "n": tokens},
    )
