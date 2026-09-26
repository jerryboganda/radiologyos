"""Live proof of the retention purge (ADR 0009, ADR 0020) as the runtime role.

Five synthetic tenants: ``ta`` past the 24-month default, ``tb`` equally old
but exempt (``retention_months = 0``), ``tc`` old but under legal hold, ``td``
past its own 2-month override, and ``te`` recent. The finder must return ids
only and exactly ``ta`` and ``td``; a dry run must delete nothing; enforce must
purge those two sources with their objects and derived rows, leave every other
tenant untouched, and be idempotent.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from apps.worker.app.datarights import retention  # noqa: E402
from apps.worker.app.datarights.jobs import DataDeps  # noqa: E402
from evals.checks._data_rights_support import (  # noqa: E402
    cleanup,
    counts,
    require_env,
    seed_content,
    seed_identity,
    seed_objects,
)
from packages.library.storage import MemoryObjectStore  # noqa: E402

TENANTS = ("ta", "tb", "tc", "td", "te")
AGE = {"ta": "25 months", "tb": "25 months", "tc": "25 months", "td": "3 months",
       "te": "1 month"}
SETTINGS = {"tb": {"retention_months": 0}, "td": {"retention_months": 2}}
DERIVED = ("sources", "source_pages", "source_blocks", "figures", "chunks", "claims", "jobs")


def _objects(store: MemoryObjectStore, tenant: UUID) -> set[str]:
    return {k for k in store.objects if k.startswith(f"tenants/{tenant}/")}


async def _seed(admin: Any, runtime: Any, store: MemoryObjectStore,
                ids: dict[str, UUID]) -> None:
    for name in TENANTS:
        t, u, s = ids[name], ids["u" + name], ids["s" + name]
        await seed_identity(admin, t, u, s, held=name == "tc")
        await seed_content(runtime, t, u, s)
        seed_objects(store, t, s)
        await admin.execute("UPDATE sources SET created_at = "
                            "now() - CAST(CAST($2 AS text) AS interval) WHERE id = $1",
                            s, AGE[name])
        if name in SETTINGS:
            await admin.execute("UPDATE tenants SET settings = CAST($2 AS jsonb) WHERE id = $1",
                                t, json.dumps(SETTINGS[name]))


async def _finder(runtime: Any, ids: dict[str, UUID]) -> None:
    ours = {ids[name] for name in TENANTS}
    rows = await runtime.fetch("SELECT * FROM app.retention_due_sources($1, 24)",
                               datetime.now(UTC))  # no tenant context: definer, ids only
    assert rows and set(rows[0].keys()) == {"tenant_id", "source_id", "months"}
    due = {(r["tenant_id"], r["source_id"], r["months"]) for r in rows if r["tenant_id"] in ours}
    assert due == {(ids["ta"], ids["sta"], 24), (ids["td"], ids["std"], 2)}, due


async def _dry_run(deps: DataDeps, admin: Any, store: MemoryObjectStore,
                   ids: dict[str, UUID]) -> None:
    before = {name: await counts(admin, ids[name]) for name in ("ta", "td")}
    objects = len(store.objects)
    result = await retention.sweep(deps, datetime.now(UTC), "dry_run", 24)
    assert result["due"] >= 2 and result["purged"] == 0
    assert len(store.objects) == objects
    for name in ("ta", "td"):
        after = await counts(admin, ids[name])
        assert after["audit_log"] == before[name]["audit_log"] + 1
        assert {k: v for k, v in after.items() if k != "audit_log"} == {
            k: v for k, v in before[name].items() if k != "audit_log"}
    row = await admin.fetchrow("SELECT actor_user_id, target_id, metadata FROM audit_log "
                               "WHERE tenant_id = $1 AND action = 'retention.dry_run'", ids["ta"])
    assert row["actor_user_id"] is None and row["target_id"] == str(ids["ta"])
    assert json.loads(row["metadata"]) == {"due_sources": 1, "months": 24}


async def _enforce(deps: DataDeps, admin: Any, store: MemoryObjectStore,
                   ids: dict[str, UUID]) -> None:
    kept = {name: (await counts(admin, ids[name]), _objects(store, ids[name]))
            for name in ("tb", "tc", "te")}
    result = await retention.sweep(deps, datetime.now(UTC), "enforce", 24)
    assert result["purged"] >= 2
    for name in ("ta", "td"):
        left = await counts(admin, ids[name])
        assert all(left[table] == 0 for table in DERIVED), left
        assert not _objects(store, ids[name])
        purged = await admin.fetchval(
            "SELECT count(*) FROM audit_log WHERE tenant_id = $1 "
            "AND action = 'retention.source_purged' AND target_id = $2",
            ids[name], str(ids["s" + name]))
        assert purged == 1
    for name, (rows, objects) in kept.items():  # exempt, held, and recent: untouched
        assert await counts(admin, ids[name]) == rows, name
        assert _objects(store, ids[name]) == objects, name
    again = await retention.sweep(deps, datetime.now(UTC), "enforce", 24)
    assert again["purged"] == 0  # idempotent
    rows = await admin.fetch("SELECT tenant_id FROM app.retention_due_sources(now(), 24)")
    assert not {r["tenant_id"] for r in rows} & {ids["ta"], ids["td"]}


async def _held_recheck(deps: DataDeps, store: MemoryObjectStore,
                        ids: dict[str, UUID]) -> None:
    before = _objects(store, ids["tc"])
    assert await retention._purge(deps, ids["tc"], ids["stc"], 24) == 0
    assert _objects(store, ids["tc"]) == before


async def _run() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = {name: uuid4() for t in TENANTS for name in (t, "u" + t, "s" + t)}
    store = MemoryObjectStore()
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    deps = DataDeps(engine=engine, store=store)
    try:
        await _seed(admin, runtime, store, ids)
        await _finder(runtime, ids)
        await _dry_run(deps, admin, store, ids)
        await _held_recheck(deps, store, ids)
        await _enforce(deps, admin, store, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await cleanup(admin, [ids[name] for name in TENANTS])
        await admin.close()


def test_retention_purge_against_runtime_role() -> None:
    require_env()
    asyncio.run(_run())
