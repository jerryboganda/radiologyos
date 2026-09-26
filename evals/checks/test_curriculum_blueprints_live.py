"""Opt-in live proof for curriculum reviews and blueprint overrides (migration 0015).

Runs as the non-privileged runtime role against a disposable database: rows of
tenant A are invisible and immutable to tenant B and to a session without a
tenant, cross-tenant inserts are refused, and curriculum decisions are
append-only for the app (no UPDATE grant).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
TABLES = ("curriculum_reviews", "exam_blueprints")
REVIEW = ("INSERT INTO curriculum_reviews (tenant_id, pack_id, pack_version, content_hash, "
          "decision, decided_by) VALUES ($1,'radiology','draft1',repeat('a',64),'approved',$2)")
BLUEPRINT = ("INSERT INTO exam_blueprints (tenant_id, blueprint_id, overrides, updated_by) "
             "VALUES ($1,'frcr_2a','{\"duration_minutes\": 90}'::jsonb,$2)")


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("curriculum/blueprint live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run this proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _seed(admin: Any, pairs: tuple[tuple[UUID, UUID], ...]) -> None:
    async with admin.transaction():
        for user, tenant in pairs:
            await admin.execute("INSERT INTO tenants (id, kind, name) VALUES ($1,'personal',$2)",
                                tenant, f"CB {tenant}")
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                user, tenant, f"cb-{user}", f"{user}@example.invalid")


async def _proof(runtime: Any, ta: UUID, tb: UUID, ua: UUID) -> None:
    await _as_tenant(runtime, ta, REVIEW, ta, ua)
    await _as_tenant(runtime, ta, BLUEPRINT, ta, ua)
    for table in TABLES:
        assert len(await _as_tenant(runtime, ta, f"SELECT 1 FROM {table}")) == 1, table
        assert await _as_tenant(runtime, tb, f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, tb, f"DELETE FROM {table} RETURNING 1") == [], table
    assert await _as_tenant(runtime, tb, "UPDATE exam_blueprints SET approved = false "
                            "RETURNING 1") == []
    for sql in (REVIEW, BLUEPRINT):  # tenant B cannot write rows for tenant A
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, tb, sql, ta, ua)
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, ta, "UPDATE curriculum_reviews SET decision = 'rejected'")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(runtime, ta, "UPDATE exam_blueprints SET approved = true")
    await _as_tenant(runtime, ta, "UPDATE curriculum_mappings SET curriculum_node_id = NULL "
                     "WHERE false")  # the new column exists and is writable


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ta, tb, ua, ub = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        await _seed(admin, ((ua, ta), (ub, tb)))
        await _proof(runtime, ta, tb, ua)
    finally:
        await runtime.close()
        async with admin.transaction():
            for table in TABLES:
                await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                    [ta, tb])
            await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", [ta, tb])
            await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [ta, tb])
        await admin.close()


def test_curriculum_and_blueprint_tables_are_tenant_isolated() -> None:
    _require_env()
    asyncio.run(_run())
