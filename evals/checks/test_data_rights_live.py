"""Opt-in live proof of account export and deletion (migration 0012, ADR 0018).

Runs the real worker code as the RLS-bound runtime role against synthetic
users that have one row in every user-owned table: ``data_jobs`` isolation,
the ids-only expiry resolver, the guarded identity eraser, a real export ZIP,
a real delete that leaves nothing of the user but one content-free audit
record and the delete job, legal-hold handling, and export expiry. The other
tenant is proven untouched throughout.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from apps.worker.app.datarights import registry  # noqa: E402
from apps.worker.app.datarights.delete import run_delete  # noqa: E402
from apps.worker.app.datarights.export import run_export  # noqa: E402
from apps.worker.app.datarights.jobs import DataDeps  # noqa: E402
from apps.worker.app.datarights.tasks import expire  # noqa: E402
from evals.checks._data_rights_support import (  # noqa: E402
    as_tenant,
    cleanup,
    counts,
    require_env,
    seed_content,
    seed_identity,
    seed_objects,
    seed_tutor_image_object,
    tutor_image_id,
)
from packages.library.storage import MemoryObjectStore, export_key  # noqa: E402


async def _new_job(runtime: Any, tenant: UUID, user: UUID, kind: str) -> UUID:
    expires = "now() + interval '7 days'" if kind == "export" else "NULL"
    rows = await as_tenant(runtime, tenant, "INSERT INTO data_jobs (tenant_id, user_id, kind, "
                           f"expires_at) VALUES ($1,$2,$3,{expires}) RETURNING id",
                           tenant, user, kind)
    return UUID(str(rows[0]["id"]))


async def _isolation(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    job = await _new_job(runtime, ta, ids["ua"], "export")
    assert await as_tenant(runtime, tb, "SELECT 1 FROM data_jobs WHERE tenant_id = $1", ta) == []
    assert await as_tenant(runtime, None, "SELECT 1 FROM data_jobs") == []
    assert await as_tenant(runtime, tb, "DELETE FROM data_jobs WHERE id = $1 RETURNING 1",
                           job) == []
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await as_tenant(runtime, tb, "INSERT INTO data_jobs (tenant_id, user_id, kind) "
                        "VALUES ($1,$2,'delete')", ta, ids["ua"])
    for tenant in (ta, tb, None):  # no running delete job: the eraser refuses
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await as_tenant(runtime, tenant, "SELECT app.erase_user_identity($1)", ids["ua"])
    due = await runtime.fetch("SELECT * FROM app.expired_data_exports($1)",
                              datetime.now(UTC) + timedelta(days=8))
    assert (ta, job) in {(r["tenant_id"], r["job_id"]) for r in due}
    assert set(due[0].keys()) == {"tenant_id", "job_id"}  # ids only, never content
    await as_tenant(runtime, ta, "DELETE FROM data_jobs WHERE id = $1", job)


def _read_zip(store: MemoryObjectStore, key: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(store.get(key)))


async def _export(deps: DataDeps, runtime: Any, store: MemoryObjectStore,
                  ids: dict[str, UUID]) -> None:
    ta, ua, sa = ids["ta"], ids["ua"], ids["sa"]
    job = await _new_job(runtime, ta, ua, "export")
    assert await run_export(deps, ta, job) == "succeeded"
    assert await run_export(deps, ta, job) == "done"  # idempotent
    row = (await as_tenant(runtime, ta, "SELECT status, object_key, byte_size, expires_at "
                           "FROM data_jobs WHERE id = $1", job))[0]
    assert row["status"] == "succeeded" and row["object_key"] == export_key(ta, job)
    assert row["expires_at"] > datetime.now(UTC) + timedelta(days=6)
    with _read_zip(store, row["object_key"]) as zf:
        names = set(zf.namelist())
        for item in registry.OWNED:
            assert f"data/{item.table}.json" in names, item.table
        for table in ("cards", "claims", "chunks", "tutor_messages", "attempts", "users"):
            assert len(json.loads(zf.read(f"data/{table}.json"))) >= 1, table
        chunk = json.loads(zf.read("data/chunks.json"))[0]
        assert chunk["embedding"] is not None  # derived data and embeddings are exported
        assert zf.read(f"files/{sa}/chest notes.pdf") == b"%PDF-synthetic"
        assert zf.read(f"figures/{sa}/00001-000.png") == b"figure-png"
        assert zf.read(f"tutor-images/{tutor_image_id(ua)}.png") == b"tutor-png"
        assert len(json.loads(zf.read("data/tutor_images.json"))) == 1
        cards_md = zf.read("notes/cards.md").decode()
        assert "Synthetic front?" in cards_md and "Synthetic chest notes, p. 1" in cards_md
        assert "Synthetic claim 1" in zf.read("notes/claims.md").decode()
        blob = b"".join(zf.read(name) for name in names)
        for other in (ids["tb"], ids["ub"], ids["sb"]):
            assert str(other).encode() not in blob  # nothing of the other tenant


async def _expiry(deps: DataDeps, runtime: Any, store: MemoryObjectStore,
                  ids: dict[str, UUID]) -> None:
    tb = ids["tb"]
    job = await _new_job(runtime, tb, ids["ub"], "export")
    store.put(export_key(tb, job), b"old-zip", "application/zip")
    await as_tenant(runtime, tb, "UPDATE data_jobs SET object_key = $2, "
                    "expires_at = now() - interval '1 minute' WHERE id = $1",
                    job, export_key(tb, job))
    assert await expire(deps, datetime.now(UTC)) >= 1
    assert export_key(tb, job) not in store.objects
    assert await as_tenant(runtime, tb, "SELECT 1 FROM data_jobs WHERE id = $1", job) == []


async def _delete(deps: DataDeps, admin: Any, runtime: Any, store: MemoryObjectStore,
                  ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    before_b = await counts(admin, tb)
    objects_b = {k for k in store.objects if k.startswith(f"tenants/{tb}/")}
    job = await _new_job(runtime, ta, ids["ua"], "delete")
    assert await run_delete(deps, ta, job) == "succeeded"
    assert await run_delete(deps, ta, job) == "done"
    left = {table: n for table, n in (await counts(admin, ta)).items() if n}
    assert left == {"audit_log": 1, "data_jobs": 1}, left
    audit = await admin.fetchrow("SELECT actor_user_id, action, target_id, metadata "
                                 "FROM audit_log WHERE tenant_id = $1", ta)
    assert audit["actor_user_id"] is None and audit["action"] == "account.erased"
    assert json.loads(audit["metadata"]) == {"identity": "deleted"}
    tenant = await admin.fetchrow("SELECT name, deleted_at FROM tenants WHERE id = $1", ta)
    assert tenant["name"] == "Deleted account" and tenant["deleted_at"] is not None
    assert not [k for k in store.objects if k.startswith(f"tenants/{ta}/")]
    assert await counts(admin, tb) == before_b  # the other tenant is untouched
    assert {k for k in store.objects if k.startswith(f"tenants/{tb}/")} == objects_b


async def _held(deps: DataDeps, admin: Any, runtime: Any, store: MemoryObjectStore,
                ids: dict[str, UUID]) -> None:
    tc, uc, sh = ids["tc"], ids["uc"], ids["sh"]
    job = await _new_job(runtime, tc, uc, "delete")
    assert await run_delete(deps, tc, job) == "succeeded"
    detail = (await as_tenant(runtime, tc, "SELECT detail FROM data_jobs WHERE id = $1",
                              job))[0]["detail"]
    detail = json.loads(detail) if isinstance(detail, str) else detail
    assert detail["held_sources"] == 1 and detail["held_source_ids"] == [str(sh)]
    assert detail["identity"] == "scrubbed"
    user = await admin.fetchrow("SELECT email, oidc_subject, display_name, deleted_at "
                                "FROM users WHERE id = $1", uc)
    assert user["email"].startswith("erased-") and user["oidc_subject"].startswith("erased:")
    assert user["display_name"] is None and user["deleted_at"] is not None
    left = await counts(admin, tc)
    assert left["sources"] == 1 and left["source_pages"] == 1  # held evidence kept
    for table in registry.DIRECT_DELETE_ORDER:
        assert left[table] == 0, table  # the user's own study data is still erased
    assert any(k.startswith(f"tenants/{tc}/sources/{sh}/") for k in store.objects)


async def _run() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = {name: uuid4() for name in ("ta", "tb", "tc", "ua", "ub", "uc", "sa", "sb", "sh")}
    store = MemoryObjectStore()
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    deps = DataDeps(engine=engine, store=store)
    try:
        for t, u, s, held in (("ta", "ua", "sa", False), ("tb", "ub", "sb", False),
                              ("tc", "uc", "sh", True)):
            await seed_identity(admin, ids[t], ids[u], ids[s], held)
            await seed_content(runtime, ids[t], ids[u], ids[s])
            seed_objects(store, ids[t], ids[s])
            seed_tutor_image_object(store, ids[t], ids[u])
        await _isolation(runtime, ids)
        await _export(deps, runtime, store, ids)
        await _expiry(deps, runtime, store, ids)
        await _delete(deps, admin, runtime, store, ids)
        await _held(deps, admin, runtime, store, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await cleanup(admin, [ids["ta"], ids["tb"], ids["tc"]])
        await admin.close()


def test_account_export_and_delete_against_runtime_role() -> None:
    require_env()
    asyncio.run(_run())
