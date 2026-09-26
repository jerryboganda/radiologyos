"""Opt-in live proof for the model-call ledger (migration 0104, ADR 0032).

Runs as the RLS-bound runtime role against disposable PostgreSQL in CI:
* ``llm_calls`` is tenant-isolated (two tenants, no-context reads nothing),
  refuses cross-tenant writes and UPDATE, and allows the erasure DELETE;
* ``ops_alerts`` accepts the new ``model_usage_limit`` kind;
* the real ledger writer raises the usage-limit spike alert exactly once past
  the threshold, and re-arms it only after an acknowledgement an hour old.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks.test_library_live import _as_tenant, _cleanup, _require_env, _seed  # noqa: E402
from packages.models.ledger import CallRecord  # noqa: E402

INSERT = ("INSERT INTO llm_calls (tenant_id, user_id, agent, route, backend, model, effort, "
          "status, duration_ms) VALUES ($1,$2,'page_parse/v2','vision','claude_code',"
          "'synthetic-model','medium',$3,1000)")


async def _isolation(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    await _as_tenant(runtime, ta, INSERT, ta, ids["ua"], "ok")
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM llm_calls") == []
    assert await _as_tenant(runtime, None, "SELECT 1 FROM llm_calls") == []
    assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM llm_calls")) == 1
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, INSERT, ta, ids["ua"], "ok")
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, ta, "UPDATE llm_calls SET status = 'error'")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(runtime, ta, INSERT, ta, ids["ua"], "maybe")
    await _as_tenant(runtime, ta, "DELETE FROM llm_calls WHERE user_id = $1", ids["ua"])
    assert await _as_tenant(runtime, ta, "SELECT 1 FROM llm_calls") == []


def _record(tenant: UUID) -> CallRecord:
    return CallRecord(agent="page_parse/v2", route="vision", backend="claude_code",
                      model="synthetic-model", effort="medium", status="usage_limit",
                      duration_ms=50, error_code="UsageLimitError", tenant_id=tenant,
                      request_id=str(uuid4()))


async def _spike(runtime_dsn: str, runtime: Any, admin: Any, ids: dict[str, UUID]) -> None:
    from apps.worker.app.ops.llm_ledger import store
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    alerts = "SELECT id, acknowledged_at FROM ops_alerts WHERE kind = 'model_usage_limit'"
    try:
        for _ in range(5):
            await store(engine, _record(ids["ta"]), 5)
        assert await _as_tenant(runtime, ids["ta"], alerts) == []  # at the threshold: quiet
        for _ in range(3):
            await store(engine, _record(ids["ta"]), 5)
        assert len(await _as_tenant(runtime, ids["ta"], alerts)) == 1  # once, not per record
        assert await _as_tenant(runtime, ids["tb"], alerts) == []
        await admin.execute("UPDATE ops_alerts SET acknowledged_at = now() - interval '2 hours' "
                            "WHERE tenant_id = $1 AND kind = 'model_usage_limit'", ids["ta"])
        await store(engine, _record(ids["ta"]), 5)
        [row] = await _as_tenant(runtime, ids["ta"], alerts)
        assert row["acknowledged_at"] is None  # re-armed for a new spike
    finally:
        await engine.dispose()


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _isolation(runtime, ids)
        await _spike(runtime_dsn, runtime, admin, ids)
    finally:
        await runtime.close()
        async with admin.transaction():
            for table in ("llm_calls", "ops_alerts"):
                await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                    [ids["ta"], ids["tb"]])
        await _cleanup(admin, ids)
        await admin.close()


def test_model_ledger_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
