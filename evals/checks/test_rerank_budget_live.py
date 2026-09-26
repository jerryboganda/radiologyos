"""Opt-in live proof for the rerank budget and graph expansion (migration 0101, ADR 0028).

Runs as the RLS-bound runtime role against disposable PostgreSQL in CI:
* ``app.voyage_model_tokens_total(model)`` counts one model across tenants and
  returns a single number; ``app.embedding_tokens_total()`` no longer counts
  rerank tokens, so each free allowance has its own cap;
* ``ops_alerts`` accepts ``rerank_budget`` alerts, still rejects unknown kinds,
  and stays tenant-isolated;
* tutor graph expansion reads only the caller's tenant: tenant B never sees
  tenant A's concepts, claims, or edges, and every claim offered carries its
  chunk, pages, and evidence span.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks.test_library_live import _cleanup, _require_env, _seed  # noqa: E402

GRAPH_TABLES = ("concept_edges", "claims", "concepts")


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _totals(runtime: Any, tenant: UUID) -> tuple[int, int]:
    emb = await _as_tenant(runtime, tenant, "SELECT * FROM app.embedding_tokens_total()")
    rer = await _as_tenant(runtime, tenant,
                           "SELECT * FROM app.voyage_model_tokens_total('rerank-2.5')")
    assert list(rer[0].keys()) == ["voyage_model_tokens_total"]  # a number, nothing else
    return int(emb[0][0]), int(rer[0][0])


async def _ledger(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    emb0, rer0 = await _totals(runtime, tb)
    for model, tokens in (("rerank-2.5", 7), ("voyage-4-large", 5)):
        await _as_tenant(runtime, ta, "INSERT INTO embedding_usage (tenant_id, day, model, "
                         "tokens, requests) VALUES ($1, DATE '2001-01-01', $2, $3, 1)",
                         ta, model, tokens)
    emb1, rer1 = await _totals(runtime, tb)  # the free tier is per account and per model
    assert (emb1 - emb0, rer1 - rer0) == (5, 7)
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM embedding_usage") == []


async def _alerts(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    await _as_tenant(runtime, ta, "INSERT INTO ops_alerts (tenant_id, kind, level) "
                     "VALUES ($1, 'rerank_budget', 'amber')", ta)
    assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM ops_alerts "
                                "WHERE kind = 'rerank_budget'")) == 1
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM ops_alerts") == []
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(runtime, ta, "INSERT INTO ops_alerts (tenant_id, kind, level) "
                         "VALUES ($1, 'bogus_budget', 'red')", ta)
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, "INSERT INTO ops_alerts (tenant_id, kind, level) "
                         "VALUES ($1, 'rerank_budget', 'red')", ta)


async def _seed_graph(runtime: Any, ids: dict[str, UUID]) -> dict[str, UUID]:
    ta, sa = ids["ta"], ids["sa"]
    g = {name: uuid4() for name in ("c1", "c2", "x", "y")}
    for n, chunk in enumerate(("c1", "c2")):
        await _as_tenant(runtime, ta, "INSERT INTO chunks (id, tenant_id, source_id, chunk_no, "
                         "page_from, page_to, text) VALUES ($1,$2,$3,$4,1,1,'synthetic')",
                         g[chunk], ta, sa, 50 + n)
    for concept, name in (("x", "Crazy paving"), ("y", "Pulmonary oedema")):
        await _as_tenant(runtime, ta, "INSERT INTO concepts (id, tenant_id, name, "
                         "normalized_name) VALUES ($1,$2,$3,lower($3))", g[concept], ta, name)
    for concept, chunk, span in (("x", "c1", "Seed on the top chunk."),
                                 ("x", "c2", "Seed fact elsewhere."),
                                 ("y", "c2", "Oedema also causes it.")):
        await _as_tenant(
            runtime, ta, "INSERT INTO claims (tenant_id, concept_id, statement, evidence_span, "
            "source_id, chunk_id, page_from, page_to, citation, agent_version) VALUES "
            "($1,$2,$3,$3,$4,$5,1,1,'{\"blocks\": []}'::jsonb,'t/v1')",
            ta, g[concept], span, sa, g[chunk])
    await _as_tenant(runtime, ta, "INSERT INTO concept_edges (tenant_id, from_concept, "
                     "to_concept, relation, source_id, citation, agent_version) VALUES "
                     "($1,$2,$3,'differential_of',$4,'{}'::jsonb,'t/v1')", ta, g["y"], g["x"], sa)
    return g


async def _graph(runtime_dsn: str, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.tutor import graph
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    g = await _seed_graph(runtime, ids)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        results = {}
        for tenant, user in (("ta", "ua"), ("tb", "ub")):
            async with AsyncSession(engine) as session:
                await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"),
                                      {"t": str(ids[tenant])})
                results[tenant] = await graph.expand(session, ids[user], [g["c1"]], "ddx")
    finally:
        await engine.dispose()
    assert [e.text for e in results["ta"]] == ["Seed fact elsewhere.", "Oedema also causes it."]
    assert all(e.chunk_id == g["c2"] and e.page_from == 1 for e in results["ta"])
    assert results["tb"] == []  # another tenant's graph is invisible


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _ledger(runtime, ids)
        await _alerts(runtime, ids)
        await _graph(runtime_dsn, runtime, ids)
    finally:
        await runtime.close()
        async with admin.transaction():
            for table in (*GRAPH_TABLES, "embedding_usage", "ops_alerts"):
                await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                    [ids["ta"], ids["tb"]])
        await _cleanup(admin, ids)
        await admin.close()


def test_rerank_budget_and_graph_expansion_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
