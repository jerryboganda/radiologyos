"""Opt-in live proof for push reminder tables (migration 0009) as the runtime role."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("notifications live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run this proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ta, tb, ua, ub = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with admin.transaction():
            await admin.execute("INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','N A'),"
                                "($2,'personal','N B')", ta, tb)
            for user, tenant in ((ua, ta), (ub, tb)):
                await admin.execute(
                    "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                    user, tenant, f"n-{user}", f"{user}@example.invalid")
        await _as_tenant(runtime, ta,
                         "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint, p256dh, "
                         "auth) VALUES ($1,$2,'https://push.example.invalid/a','p'||repeat('x',20),"
                         "'authauthauth')", ta, ua)
        await _as_tenant(runtime, ta,
                         "INSERT INTO notification_settings (tenant_id, user_id, reminder_time, "
                         "timezone) VALUES ($1,$2,'00:00','UTC')", ta, ua)
        for table in ("push_subscriptions", "notification_settings"):
            assert await _as_tenant(runtime, tb, f"SELECT 1 FROM {table}") == [], table
            assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
            assert len(await _as_tenant(runtime, ta, f"SELECT 1 FROM {table}")) == 1, table
            assert await _as_tenant(runtime, tb, f"DELETE FROM {table} RETURNING 1") == []
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, tb,
                             "INSERT INTO notification_settings (tenant_id, user_id) "
                             "VALUES ($1,$2)", ta, ua)
        due = await runtime.fetch("SELECT * FROM app.due_reminders($1)", datetime.now(UTC))
        pairs = {(row["tenant_id"], row["user_id"]) for row in due}
        assert (ta, ua) in pairs
        assert set(due[0].keys()) == {"tenant_id", "user_id"}  # ids only, never content
    finally:
        await runtime.close()
        async with admin.transaction():
            for table in ("push_subscriptions", "notification_settings"):
                await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                    [ta, tb])
            await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", [ta, tb])
            await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [ta, tb])
        await admin.close()


def test_notification_tables_are_tenant_isolated() -> None:
    _require_env()
    asyncio.run(_run())
