"""Opt-in live PostgreSQL proof of the tenant RLS boundary (ADR 0001, 0008, 0022).

Two layers, both run as the non-privileged runtime role:

* a catalog proof over **every** table that carries ``tenant_id`` (plus
  ``tenants``): ENABLE + FORCE RLS, not owned by the runtime role, blind without
  a valid tenant context, and refusing foreign-tenant inserts. The table list
  comes from ``pg_catalog``, so new tables are covered automatically;
* the original two-tenant read/update/delete/insert matrix for the M0 tables,
  with a reviewed Core source.

``Verify production RLS`` runs this module over a tunnel to the production
database; CI runs it against a freshly migrated database.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks._rls_catalog import (  # noqa: E402
    assert_blind_without_context,
    assert_catalog_forced,
    assert_inserts_denied,
    assert_runtime_role,
)
from evals.checks._rls_m0_support import (  # noqa: E402
    M0_TABLES,
    M0Fixture,
    cleanup,
    seed,
    source_hash,
)

_UPDATED = "WITH changed AS ({}) SELECT count(*) FROM changed"


def _require_dsns() -> tuple[str, str]:
    required = {"RADBRAIN_RLS_ADMIN_DATABASE_URL", "RADBRAIN_RLS_RUNTIME_DATABASE_URL"}
    if not required.issubset(os.environ):
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("RLS proof requires disposable admin/runtime PostgreSQL URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run live RLS proof")
    return (
        os.environ["RADBRAIN_RLS_ADMIN_DATABASE_URL"],
        os.environ["RADBRAIN_RLS_RUNTIME_DATABASE_URL"],
    )


async def _as_tenant(
    runtime: Any, tenant: UUID | str, check: Callable[[], Awaitable[None]]
) -> None:
    async with runtime.transaction():
        await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        await check()


async def _ids(runtime: Any, sql: str) -> set[Any]:
    return {row[0] for row in await runtime.fetch(sql)}


async def _assert_zero_or_denied(runtime: Any, fx: M0Fixture, sql: str, *args: Any) -> None:
    async with runtime.transaction():
        await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(fx.tenant_a))
        try:
            result = await runtime.fetchval(sql, *args)
        except asyncpg.PostgresError as denied:
            assert denied.sqlstate == "42501"
        else:
            assert result == 0, sql


async def _assert_denied(runtime: Any, fx: M0Fixture, sql: str, *args: Any) -> None:
    async with runtime.transaction():
        await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(fx.tenant_a))
        with pytest.raises(asyncpg.PostgresError) as denied:
            await runtime.execute(sql, *args)
        assert denied.value.sqlstate == "42501", sql


async def _assert_m0_blind(runtime: Any) -> None:
    for table in M0_TABLES:
        assert await runtime.fetchval(f"SELECT count(*) FROM {table}") == 0  # nosec B608
    async with runtime.transaction():
        await runtime.execute("SELECT set_config('app.tenant_id', 'not-a-uuid', true)")
        assert await runtime.fetchval("SELECT count(*) FROM sources") == 0
        assert await runtime.fetchval("SELECT count(*) FROM users") == 0


async def _assert_tenant_a_view(runtime: Any, fx: M0Fixture) -> None:
    assert await _ids(runtime, "SELECT id FROM tenants") == {fx.tenant_a}
    assert await _ids(runtime, "SELECT id FROM users") == {fx.user_a}
    assert await _ids(runtime, "SELECT user_id FROM memberships") == {fx.user_a}
    assert await _ids(runtime, "SELECT id FROM jobs") == {fx.job_a}
    assert await _ids(runtime, "SELECT id FROM job_steps") == {fx.step_a}
    assert await _ids(runtime, "SELECT target_id FROM audit_log") == {str(fx.audit_target_a)}
    assert await _ids(runtime, "SELECT id FROM sources") == {fx.source_a, fx.core_source}
    retitle = _UPDATED.format("UPDATE sources SET title = 'forbidden' WHERE id = $1 RETURNING 1")
    assert await runtime.fetchval(retitle, fx.source_b) == 0
    assert await runtime.fetchval(retitle, fx.core_source) == 0
    with pytest.raises(asyncpg.PostgresError) as denied:
        await runtime.execute(
            "INSERT INTO sources "
            "(tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
            "title, status, rights_status) VALUES "
            "($1, $2, 'note', 'private', $3, $4, 'forbidden', 'ready', 'unverified')",
            fx.tenant_b,
            fx.user_b,
            source_hash("forbidden"),
            f"tenants/{fx.tenant_b}/forbidden",
        )
    assert denied.value.sqlstate == "42501"


async def _assert_tenant_b_view(runtime: Any, fx: M0Fixture) -> None:
    assert await _ids(runtime, "SELECT id FROM tenants") == {fx.tenant_b}
    assert await _ids(runtime, "SELECT id FROM users") == {fx.user_b, fx.user_b_extra}
    assert await _ids(runtime, "SELECT user_id FROM memberships") == {fx.user_b}
    assert await _ids(runtime, "SELECT id FROM sources") == {fx.source_b, fx.core_source}
    assert await _ids(runtime, "SELECT id FROM jobs") == {fx.job_b, fx.job_b_probe}
    assert await _ids(runtime, "SELECT id FROM job_steps") == {fx.step_b}
    assert await _ids(runtime, "SELECT target_id FROM audit_log") == {str(fx.audit_target_b)}


async def _assert_cross_updates_and_deletes(runtime: Any, fx: M0Fixture) -> None:
    updates = (
        ("UPDATE tenants SET name = 'forbidden' WHERE id = $1 RETURNING 1", fx.tenant_b),
        ("UPDATE users SET display_name = 'forbidden' WHERE id = $1 RETURNING 1", fx.user_b),
        (
            "UPDATE memberships SET active = NOT active WHERE user_id = $1 RETURNING 1",
            fx.user_b,
        ),
        ("UPDATE jobs SET status = 'failed' WHERE id = $1 RETURNING 1", fx.job_b),
        ("UPDATE job_steps SET status = 'failed' WHERE id = $1 RETURNING 1", fx.step_b),
    )
    deletes = (
        ("DELETE FROM sources WHERE id = $1 RETURNING 1", fx.source_b),
        ("DELETE FROM users WHERE id = $1 RETURNING 1", fx.user_b),
        ("DELETE FROM jobs WHERE id = $1 RETURNING 1", fx.job_b),
        ("DELETE FROM job_steps WHERE id = $1 RETURNING 1", fx.step_b),
    )
    for statement, parameter in (*updates, *deletes):
        await _assert_zero_or_denied(runtime, fx, _UPDATED.format(statement), parameter)


async def _assert_cross_inserts_denied(runtime: Any, fx: M0Fixture) -> None:
    await _assert_denied(
        runtime, fx, "INSERT INTO tenants (id, kind, name) VALUES ($1, 'personal', 'x')", uuid4()
    )
    await _assert_denied(
        runtime,
        fx,
        "INSERT INTO users (id, tenant_id, oidc_subject, email) "
        "VALUES ($1, $2, 'synthetic-forbidden', 'forbidden@example.invalid')",
        uuid4(),
        fx.tenant_b,
    )
    await _assert_denied(
        runtime,
        fx,
        "INSERT INTO memberships (id, tenant_id, user_id, role) VALUES ($1, $2, $3, 'student')",
        fx.membership_b_extra,
        fx.tenant_b,
        fx.user_b_extra,
    )
    await _assert_denied(
        runtime,
        fx,
        "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key) "
        "VALUES ($1, $2, $3, 'ingest_source', $4)",
        uuid4(),
        fx.tenant_b,
        fx.source_b,
        f"forbidden-{uuid4()}",
    )
    await _assert_denied(
        runtime,
        fx,
        "INSERT INTO job_steps (id, tenant_id, job_id, entity_id, step, pipeline_version) "
        "VALUES ($1, $2, $3, $4, 'render_pages', 1)",
        uuid4(),
        fx.tenant_b,
        fx.job_b_probe,
        fx.source_b,
    )
    await _assert_denied(
        runtime,
        fx,
        "INSERT INTO audit_log (tenant_id, action, target_type, target_id) "
        "VALUES ($1, 'rls.forbidden', 'source', $2)",
        fx.tenant_b,
        str(uuid4()),
    )
    await _assert_denied(
        runtime,
        fx,
        "UPDATE audit_log SET action = 'forbidden' WHERE target_id = $1",
        str(fx.audit_target_b),
    )


async def _assert_m0_matrix(admin_dsn: str, runtime_dsn: str) -> None:
    fx = M0Fixture()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    try:
        await assert_runtime_role(runtime)
        await seed(admin, fx)
        await _assert_m0_blind(runtime)
        await _as_tenant(runtime, fx.tenant_a, lambda: _assert_tenant_a_view(runtime, fx))
        await _assert_cross_updates_and_deletes(runtime, fx)
        await _assert_cross_inserts_denied(runtime, fx)
        await _assert_m0_blind(runtime)
        await _as_tenant(runtime, fx.tenant_b, lambda: _assert_tenant_b_view(runtime, fx))
    finally:
        await runtime.close()
        await cleanup(admin, fx)
        await admin.close()


async def _assert_catalog(runtime_dsn: str) -> None:
    runtime = await asyncpg.connect(runtime_dsn)
    try:
        await assert_runtime_role(runtime)
        tables = await assert_catalog_forced(runtime)
        await assert_blind_without_context(runtime, tables)
        await assert_inserts_denied(runtime, tables)
    finally:
        await runtime.close()


def test_every_tenant_table_is_forced_and_blind_without_context() -> None:
    _, runtime_dsn = _require_dsns()
    asyncio.run(_assert_catalog(runtime_dsn))


def test_two_tenant_rls_against_runtime_role() -> None:
    admin_dsn, runtime_dsn = _require_dsns()
    asyncio.run(_assert_m0_matrix(admin_dsn, runtime_dsn))
