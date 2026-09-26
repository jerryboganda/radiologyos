"""Opt-in live proof for the library tables and pipeline (migration 0004).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* every new tenant table hides tenant A's rows from tenant B, rejects writes
  with a foreign tenant_id, and shows nothing without tenant context;
* the real ingestion pipeline turns a synthetic PDF into pages, blocks and
  chunks, marks the source ready, and hybrid search returns a cited hit only
  to its owner.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from apps.api.tests.pdf_fixture import make_pdf  # noqa: E402
from packages.library import storage  # noqa: E402

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("library live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the library proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "sb")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Lib A'),"
            "($2,'personal','Lib B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"lib-{ids[user]}", f"{ids[user]}@example.invalid")
        for source, tenant, user in (("sa", "ta", "ua"), ("sb", "tb", "ub")):
            await admin.execute(
                "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, "
                "storage_key, title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic')",
                ids[source], ids[tenant], ids[user], uuid4().hex + uuid4().hex,
                storage.original_key(ids[tenant], ids[source], "pdf"))
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("chunks", "figures", "source_blocks", "source_pages", "job_steps",
                      "jobs", "audit_log", "sources"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


INSERTS = {
    "source_pages": "INSERT INTO source_pages (tenant_id, source_id, page_no) VALUES ($1,$2,1)",
    "source_blocks": "INSERT INTO source_blocks (tenant_id, source_id, page_no, block_no, kind, "
                     "text, bbox, origin) VALUES ($1,$2,1,0,'paragraph','x','{0,0,1,1}','native')",
    "figures": "INSERT INTO figures (tenant_id, source_id, page_no, figure_no, bbox) "
               "VALUES ($1,$2,1,0,'{0,0,1,1}')",
    "chunks": "INSERT INTO chunks (tenant_id, source_id, chunk_no, page_from, page_to, text) "
              "VALUES ($1,$2,0,1,1,'alveolar proteinosis')",
}


async def _rls_proof(admin: Any, runtime: Any, ids: dict[str, UUID]) -> None:
    for table, sql in INSERTS.items():
        await _as_tenant(runtime, ids["ta"], sql, ids["ta"], ids["sa"])
        assert await _as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}")) == 1, table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, ids["tb"], sql, ids["ta"], ids["sa"])
        moved = await _as_tenant(
            runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 RETURNING 1", ids["tb"])
        assert moved == [], table
        deleted = await _as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1")
        assert deleted == [], table
    await _as_tenant(runtime, ids["ta"], "DELETE FROM chunks")


async def _pipeline_proof(runtime_dsn: str, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.library.search import hybrid_search
    from apps.worker.app.ingest.steps import Deps, run_ingest
    from sqlalchemy.ext.asyncio import create_async_engine

    store = storage.MemoryObjectStore()
    key = storage.original_key(ids["ta"], ids["sa"], "pdf")
    store.put(key, make_pdf([["Pulmonary alveolar proteinosis", "Crazy paving on HRCT"],
                             ["Sarcoidosis perilymphatic nodules"]]), "application/pdf")
    job = uuid4()
    await _as_tenant(
        runtime, ids["ta"],
        "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key) "
        "VALUES ($1,$2,$3,'ingest_source',$4)", job, ids["ta"], ids["sa"], f"ingest:{job}")
    url = runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    try:
        deps = Deps(engine=engine, store=store, transport=None, embedder=None)
        assert await run_ingest(deps, ids["ta"], job) == "succeeded"
        assert await run_ingest(deps, ids["ta"], job) == "succeeded"  # idempotent re-run
        from apps.worker.app.ingest.db import tenant_tx

        async with tenant_tx(engine, ids["ta"]) as session:
            hits = await hybrid_search(session, ids["ua"], "crazy paving", None)
        async with tenant_tx(engine, ids["tb"]) as session:
            leaked = await hybrid_search(session, ids["ub"], "crazy paving", None)
    finally:
        await engine.dispose()
    assert hits and hits[0]["page_from"] == 1 and hits[0]["block_refs"]
    assert leaked == []
    status = await _as_tenant(runtime, ids["ta"], "SELECT status, page_count FROM sources "
                              "WHERE id = $1", ids["sa"])
    assert (status[0]["status"], status[0]["page_count"]) == ("ready", 2)
    steps = dict(await _as_tenant(runtime, ids["ta"],
                                  "SELECT step, status FROM job_steps WHERE job_id = $1", job))
    assert steps["render_pages"] == "succeeded" and steps["chunk"] == "succeeded"
    assert steps["embed_index"] == "skipped" and steps["parse_layout"] == "skipped"


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _rls_proof(admin, runtime, ids)
        await _pipeline_proof(runtime_dsn, runtime, ids)
    finally:
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_library_tables_and_pipeline_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
