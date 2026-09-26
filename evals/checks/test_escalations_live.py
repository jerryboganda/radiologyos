"""Opt-in live proof for owner escalations (migration 0106, ADR 0037).

Runs as the RLS-bound runtime role against disposable PostgreSQL in CI:
* ``model_escalations`` is tenant-isolated (two tenants, no-context reads
  nothing) and refuses cross-tenant writes and unknown statuses;
* the real worker helpers record an item once, re-open it after it is done,
  raise the owner's approval alert once, and read approved units back;
* ``ops_alerts`` accepts ``chatgpt_quota`` (the quota-pause alert).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks.test_library_live import _as_tenant, _cleanup, _require_env, _seed  # noqa: E402

INSERT = ("INSERT INTO model_escalations (tenant_id, source_id, agent, unit, reason, status) "
          "VALUES ($1,$2,'page_parse','page:3','low_text_coverage',$3)")


async def _isolation(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    await _as_tenant(runtime, ta, INSERT, ta, ids["sa"], "pending")
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM model_escalations") == []
    assert await _as_tenant(runtime, None, "SELECT 1 FROM model_escalations") == []
    assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM model_escalations")) == 1
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, INSERT, ta, ids["sa"], "pending")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(runtime, ta, "UPDATE model_escalations SET status = 'maybe'")
    await _as_tenant(runtime, ta, "DELETE FROM model_escalations")


async def _helpers(runtime_dsn: str, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.worker.app.ingest.db import tenant_tx
    from apps.worker.app.ops import escalations
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    ta, source = ids["ta"], ids["sa"]
    alerts = "SELECT detail FROM ops_alerts WHERE kind = 'owner_approval'"
    try:
        await escalations.escalate(engine, ta, source, "image_case", "page:4", "empty_reading")
        await escalations.escalate(engine, ta, source, "image_case", "page:4", "empty_reading")
        await escalations.escalate(engine, ta, source, "page_parse", "page:5", "low_coverage")
        assert len(await _as_tenant(runtime, ta, alerts)) == 1  # one alert per batch
        assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM model_escalations")) == 2
        await _as_tenant(runtime, ta, "UPDATE model_escalations SET status = 'approved' "
                                      "WHERE agent = 'image_case'")
        async with tenant_tx(engine, ta) as session:
            assert await escalations.approved_units(session, source, "image_case") == {"page:4"}
            await escalations.mark_done(session, source, "image_case", "page:4")
            assert await escalations.approved_units(session, source, "image_case") == set()
        await escalations.escalate(engine, ta, source, "image_case", "page:4", "again")
        [row] = await _as_tenant(runtime, ta, "SELECT status, reason FROM model_escalations "
                                              "WHERE agent = 'image_case'")
        assert (row["status"], row["reason"]) == ("pending", "again")  # re-opened
        await escalations.quota_paused(engine, ta, "chatgpt", time.time() + 600)
        assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM ops_alerts "
                                                 "WHERE kind = 'chatgpt_quota'")) == 1
    finally:
        await engine.dispose()


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _isolation(runtime, ids)
        await _helpers(runtime_dsn, runtime, ids)
    finally:
        await runtime.close()
        async with admin.transaction():
            for table in ("model_escalations", "ops_alerts"):
                await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                    [ids["ta"], ids["tb"]])
        await _cleanup(admin, ids)
        await admin.close()


def test_escalations_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
