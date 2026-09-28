"""Opt-in live proof for the red review list's evidence and upkeep (ADR 0041).

Runs as the RLS-bound runtime role against disposable PostgreSQL in CI:
* the owner's verdict column refuses unknown verdicts (migration 0108);
* the red list's evidence queries (summary, items with page detail, facts)
  run against the real schema and see only the caller's tenant;
* ``prune`` takes a page every model failed, and since read, off the list;
* ``redo_approved`` closes an approved section that no longer exists.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks.test_library_live import _as_tenant, _cleanup, _require_env, _seed  # noqa: E402

ITEM = ("INSERT INTO model_escalations (tenant_id, source_id, agent, unit, reason, status) "
        "VALUES ($1,$2,$3,$4,$5,$6)")


async def _prepare(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, sa = ids["ta"], ids["sa"]
    await _as_tenant(runtime, ta, "INSERT INTO source_pages (tenant_id, source_id, page_no, "
                                  "native_text, vision_status) VALUES ($1,$2,3,'own','done')",
                     ta, sa)
    await _as_tenant(runtime, ta, ITEM, ta, sa, "page_parse", "page:3", "all_models_failed",
                     "review")
    await _as_tenant(runtime, ta, ITEM, ta, sa, "image_case", "page:3", "empty_reading",
                     "review")
    await _as_tenant(runtime, ta, ITEM, ta, sa, "knowledge_extract", "chunk:" + "0" * 32,
                     "unsupported_claims", "approved")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(runtime, ta, "UPDATE model_escalations SET owner_verdict = 'maybe'")


async def _queries(runtime_dsn: str, ids: dict[str, UUID]) -> None:
    from apps.api.app.library import red_review
    from apps.worker.app.ingest.db import tenant_tx
    from apps.worker.app.ops import red_list_ops
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    ta, tb, ua = ids["ta"], ids["tb"], ids["ua"]
    try:
        async with tenant_tx(engine, ta) as session:
            [summary] = await red_review.summary(session, ua)
            assert (summary["open_pages"], summary["open_figures"]) == (1, 1)
            items = await red_review.items(session, ua, "open", None, None, 50)
            page = next(i for i in items if i["kind"] == "page")
            assert (page["page_from"], page["own_text"], page["page_status"]) == (3, "own", "done")
            assert await red_review.facts(session, ua, "open", None, 50) == []
        async with tenant_tx(engine, tb) as session:  # the other tenant sees nothing
            assert await red_review.items(session, ids["ub"], "open", None, None, 50) == []
        assert await red_list_ops.prune(engine, ta, ua) == 1  # the page has since been read
        redo = await red_list_ops.redo_approved(engine, ta, ua)
        assert (redo["section_gone"], redo["queued_for_opus"]) == (1, 0)
    finally:
        await engine.dispose()


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _prepare(runtime, ids)
        await _queries(runtime_dsn, ids)
    finally:
        await runtime.close()
        async with admin.transaction():
            await admin.execute("DELETE FROM model_escalations WHERE tenant_id = ANY($1::uuid[])",
                                [ids["ta"], ids["tb"]])
        await _cleanup(admin, ids)
        await admin.close()


def test_red_review_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
