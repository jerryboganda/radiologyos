"""Opt-in live proof for embedding cost controls (migration 0013, ADR 0019).

Runs as the RLS-bound runtime role against disposable PostgreSQL in CI:
* embedding_cache, embedding_usage and ops_alerts are tenant-isolated and
  app.embedding_tokens_total() returns a single number;
* the real pipeline pays once per unique text: re-chunking unchanged text and
  a finished-source re-run make zero paid calls;
* at the hard cap no request is sent, the step is skipped, and a red alert is
  recorded exactly once.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from apps.api.tests.pdf_fixture import make_pdf  # noqa: E402
from evals.checks.test_library_live import _cleanup, _require_env, _seed  # noqa: E402
from packages.library import storage  # noqa: E402
from packages.models.embeddings import BatchResult  # noqa: E402
from packages.models.routing import EmbeddingBudget  # noqa: E402

BUDGET = EmbeddingBudget(hard_cap_tokens=195_000_000, warn_tokens=150_000_000)
NEW_TABLES = ("embedding_cache", "embedding_usage", "ops_alerts")


@dataclass
class CountingEmbedder:
    """Stands in for the paid API; records every text it is asked to embed."""

    model: str = "voyage-4-large"
    dimensions: int = 1024
    texts: list[str] = field(default_factory=list)

    def available(self) -> bool:
        return True

    def embed_batch(self, texts: list[str], input_type: str) -> BatchResult:
        self.texts.extend(texts)
        return BatchResult([[0.001 * (i + 1)] * 1024 for i in range(len(texts))], 10 * len(texts))


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _isolation(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    await _as_tenant(runtime, ta, "INSERT INTO embedding_cache (tenant_id, content_sha256, model, "
                     "dimensions, embedding) VALUES ($1, repeat('b', 64), 'm', 1024, "
                     "array_fill(0.1::real, ARRAY[1024])::vector)", ta)
    await _as_tenant(runtime, ta, "INSERT INTO embedding_usage (tenant_id, day, model, tokens, "
                     "requests) VALUES ($1, CURRENT_DATE, 'm', 5, 1)", ta)
    await _as_tenant(runtime, ta, "INSERT INTO ops_alerts (tenant_id, kind, level) "
                     "VALUES ($1, 'embedding_budget', 'amber')", ta)
    for table in NEW_TABLES:
        assert await _as_tenant(runtime, tb, f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ta, f"SELECT 1 FROM {table}")) == 1, table
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, "INSERT INTO ops_alerts (tenant_id, kind, level) "
                         "VALUES ($1, 'embedding_budget', 'red')", ta)
    total = await _as_tenant(runtime, tb, "SELECT * FROM app.embedding_tokens_total()")
    assert list(total[0].keys()) == ["embedding_tokens_total"]  # a number, nothing else
    assert total[0][0] >= 5  # counts every tenant: the free tier is per account


async def _pay_once(runtime_dsn: str, runtime: Any, ids: dict[str, UUID]) -> CountingEmbedder:
    from apps.worker.app.ingest import steps
    from sqlalchemy.ext.asyncio import create_async_engine

    store = storage.MemoryObjectStore()
    store.put(storage.original_key(ids["ta"], ids["sa"], "pdf"),
              make_pdf([["Pulmonary alveolar proteinosis", "Crazy paving"],
                        ["Pulmonary alveolar proteinosis", "Crazy paving"]]), "application/pdf")
    job = uuid4()
    await _as_tenant(runtime, ids["ta"], "INSERT INTO jobs (id, tenant_id, entity_id, kind, "
                     "idempotency_key) VALUES ($1,$2,$3,'ingest_source',$4)",
                     job, ids["ta"], ids["sa"], f"ingest:{job}")
    fake = CountingEmbedder()
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        deps = steps.Deps(engine=engine, store=store, transport=None,
                          embedder=fake, budget=BUDGET)  # type: ignore[arg-type]
        assert await steps.run_ingest(deps, ids["ta"], job) == "succeeded"
        first = len(fake.texts)
        assert first >= 1
        await steps._chunk(deps, {"id": job, "tenant_id": ids["ta"], "entity_id": ids["sa"],
                                  "pipeline_version": 1})
        assert await steps.run_ingest(deps, ids["ta"], job) == "succeeded"
        assert len(fake.texts) == first  # re-chunked identical text: served from the cache
    finally:
        await engine.dispose()
    rows = await _as_tenant(runtime, ids["ta"], "SELECT count(*) FILTER (WHERE embedding IS NULL) "
                            "AS missing, count(DISTINCT content_sha256) AS uniq FROM chunks")
    assert rows[0]["missing"] == 0 and rows[0]["uniq"] == len(set(fake.texts))
    return fake


async def _hard_stop(runtime_dsn: str, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.worker.app.ingest.embedding import embed_pending
    from packages.models.budget import EmbeddingBudgetExhausted
    from sqlalchemy.ext.asyncio import create_async_engine

    await _as_tenant(runtime, ids["ta"], "INSERT INTO embedding_usage (tenant_id, day, model, "
                     "tokens, requests) VALUES ($1, DATE '2000-01-01', 'voyage-4-large', "
                     "195000000, 1)", ids["ta"])
    await _as_tenant(runtime, ids["ta"], "INSERT INTO chunks (tenant_id, source_id, chunk_no, "
                     "page_from, page_to, text) VALUES ($1,$2,99,1,1,'Brand new unseen text')",
                     ids["ta"], ids["sa"])
    fake = CountingEmbedder()
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        for _ in range(2):
            with pytest.raises(EmbeddingBudgetExhausted):
                await embed_pending(engine, fake, BUDGET, ids["ta"], ids["sa"])  # type: ignore[arg-type]
    finally:
        await engine.dispose()
    assert fake.texts == []  # nothing was sent past the cap
    red = await _as_tenant(runtime, ids["ta"], "SELECT level FROM ops_alerts "
                           "WHERE kind = 'embedding_budget' AND level = 'red'")
    assert len(red) == 1  # recorded once, not per attempt


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _isolation(runtime, ids)
        await _pay_once(runtime_dsn, runtime, ids)
        await _hard_stop(runtime_dsn, runtime, ids)
    finally:
        await runtime.close()
        async with admin.transaction():
            for table in NEW_TABLES:
                await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                    [ids["ta"], ids["tb"]])
        await _cleanup(admin, ids)
        await admin.close()


def test_embedding_cost_controls_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
