"""Opt-in live PostgreSQL proof for the M0 tenant RLS boundary."""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any
from uuid import uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

_CORE_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _source_hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


async def _assert_runtime_role(runtime: Any) -> None:
    role = await runtime.fetchrow(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
        "FROM pg_roles WHERE rolname = current_user"
    )
    assert role is not None
    assert not any(tuple(role))
    assert not await runtime.fetchval(
        "SELECT pg_has_role(current_user, 'radbrain_migrator', 'member')"
    )
    owners = await runtime.fetch(
        "SELECT c.relname, pg_get_userbyid(c.relowner) AS owner "
        "FROM pg_class AS c "
        "WHERE c.relname = ANY($1::text[])",
        ["tenants", "users", "memberships", "sources", "jobs", "job_steps", "audit_log"],
    )
    assert owners
    assert all(row["owner"] != "radbrain_app" for row in owners)


async def _cleanup(admin: Any, tenants: list[Any], sources: list[Any], users: list[Any]) -> None:
    by_tenant = ("audit_log", "job_steps", "jobs")
    async with admin.transaction():
        for table in by_tenant:
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM sources WHERE id = ANY($1::uuid[])", sources)
        await admin.execute("DELETE FROM memberships WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", users)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _assert_tenant_isolation() -> None:
    admin_dsn = os.environ["RADBRAIN_RLS_ADMIN_DATABASE_URL"]
    runtime_dsn = os.environ["RADBRAIN_RLS_RUNTIME_DATABASE_URL"]
    tenant_a = uuid4()
    tenant_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    source_a = uuid4()
    source_b = uuid4()
    core_source = uuid4()
    job_a, job_b, job_b_probe = uuid4(), uuid4(), uuid4()
    step_a, step_b = uuid4(), uuid4()
    user_b_extra = uuid4()
    membership_b_extra, audit_target_a, audit_target_b = uuid4(), uuid4(), uuid4()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    try:
        await _assert_runtime_role(runtime)

        async with admin.transaction():
            await admin.execute(
                "INSERT INTO tenants (id, kind, name) VALUES "
                "($1, 'personal', 'RLS Tenant A'), ($2, 'personal', 'RLS Tenant B')",
                tenant_a,
                tenant_b,
            )
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES "
                "($1, $3, 'synthetic-rls-a', 'a@example.invalid'), "
                "($2, $4, 'synthetic-rls-b', 'b@example.invalid')",
                user_a,
                user_b,
                tenant_a,
                tenant_b,
            )
            await admin.execute(
                "INSERT INTO memberships (tenant_id, user_id, role) VALUES "
                "($1, $2, 'student'), ($3, $4, 'student')",
                tenant_a,
                user_a,
                tenant_b,
                user_b,
            )
            await admin.execute(
                "INSERT INTO sources "
                "(id, tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
                "title, status, rights_status) VALUES "
                "($1, $2, $3, 'note', 'private', $4, $5, 'Tenant A', 'ready', "
                "'unverified'), "
                "($6, $7, $8, 'note', 'private', $9, $10, 'Tenant B', 'ready', "
                "'unverified'), "
                "($11, $12, NULL, 'note', 'core', $13, NULL, 'Reviewed Core', "
                "'ready', 'licensed')",
                source_a,
                tenant_a,
                user_a,
                _source_hash("a"),
                f"tenants/{tenant_a}/synthetic-a",
                source_b,
                tenant_b,
                user_b,
                _source_hash("b"),
                f"tenants/{tenant_b}/synthetic-b",
                core_source,
                _CORE_TENANT_ID,
                _source_hash("core"),
            )
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES "
                "($1, $2, 'synthetic-rls-b-extra', 'b-extra@example.invalid')",
                user_b_extra,
                tenant_b,
            )
            await admin.execute(
                "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key) VALUES "
                "($1, $2, $3, 'ingest_source', $4), "
                "($5, $6, $7, 'ingest_source', $8), "
                "($9, $6, $7, 'ingest_source', $10)",
                job_a,
                tenant_a,
                source_a,
                f"rls-job-{job_a}",
                job_b,
                tenant_b,
                source_b,
                f"rls-job-{job_b}",
                job_b_probe,
                f"rls-job-{job_b_probe}",
            )
            await admin.execute(
                "INSERT INTO job_steps "
                "(id, tenant_id, job_id, entity_id, step, pipeline_version, status) VALUES "
                "($1, $2, $3, $4, 'upload_dedupe_scan', 1, 'succeeded'), "
                "($5, $6, $7, $8, 'upload_dedupe_scan', 1, 'succeeded')",
                step_a,
                tenant_a,
                job_a,
                source_a,
                step_b,
                tenant_b,
                job_b,
                source_b,
            )
            await admin.execute(
                "INSERT INTO audit_log (tenant_id, action, target_type, target_id) VALUES "
                "($1, 'rls.read', 'source', $2), ($3, 'rls.read', 'source', $4)",
                tenant_a,
                str(audit_target_a),
                tenant_b,
                str(audit_target_b),
            )

        async def assert_denied(statement: str, *parameters: Any) -> None:
            async with runtime.transaction():
                await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_a))
                with pytest.raises(asyncpg.PostgresError) as denied:
                    await runtime.execute(statement, *parameters)
                assert denied.value.sqlstate == "42501"

        async def assert_zero(query: str, *parameters: Any) -> None:
            async with runtime.transaction():
                await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_a))
                try:
                    result = await runtime.fetchval(query, *parameters)
                except asyncpg.PostgresError as denied:
                    assert denied.sqlstate == "42501"
                else:
                    assert result == 0

        for table in (
            "tenants",
            "users",
            "memberships",
            "sources",
            "jobs",
            "job_steps",
            "audit_log",
        ):
            assert await runtime.fetchval(f"SELECT count(*) FROM {table}") == 0

        async with runtime.transaction():
            await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_a))
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM tenants")} == {
                tenant_a
            }
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM users")} == {user_a}
            assert {
                row["user_id"] for row in await runtime.fetch("SELECT user_id FROM memberships")
            } == {user_a}
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM jobs")} == {job_a}
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM job_steps")} == {
                step_a
            }
            assert {
                row["target_id"] for row in await runtime.fetch("SELECT target_id FROM audit_log")
            } == {str(audit_target_a)}
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM sources")} == {
                source_a,
                core_source,
            }
            assert (
                await runtime.fetchval(
                    "WITH updated AS (UPDATE sources SET title = 'forbidden' "
                    "WHERE id = $1 RETURNING 1) SELECT count(*) FROM updated",
                    source_b,
                )
                == 0
            )
            assert (
                await runtime.fetchval(
                    "WITH updated AS (UPDATE sources SET title = 'forbidden' "
                    "WHERE id = $1 RETURNING 1) SELECT count(*) FROM updated",
                    core_source,
                )
                == 0
            )
            with pytest.raises(asyncpg.PostgresError) as denied:
                await runtime.execute(
                    "INSERT INTO sources "
                    "(tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
                    "title, status, rights_status) VALUES "
                    "($1, $2, 'note', 'private', $3, $4, 'forbidden', 'ready', 'unverified')",
                    tenant_b,
                    user_b,
                    _source_hash("forbidden"),
                    f"tenants/{tenant_b}/forbidden",
                )
            assert denied.value.sqlstate == "42501"
        for query, parameter in (
            (
                "WITH updated AS (UPDATE tenants SET name = 'forbidden' "
                "WHERE id = $1 RETURNING 1) SELECT count(*) FROM updated",
                tenant_b,
            ),
            (
                "WITH updated AS (UPDATE users SET display_name = 'forbidden' "
                "WHERE id = $1 RETURNING 1) SELECT count(*) FROM updated",
                user_b,
            ),
            (
                "WITH updated AS (UPDATE memberships SET active = NOT active "
                "WHERE user_id = $1 RETURNING 1) SELECT count(*) FROM updated",
                user_b,
            ),
            (
                "WITH updated AS (UPDATE jobs SET status = 'failed' "
                "WHERE id = $1 RETURNING 1) SELECT count(*) FROM updated",
                job_b,
            ),
            (
                "WITH updated AS (UPDATE job_steps SET status = 'failed' "
                "WHERE id = $1 RETURNING 1) SELECT count(*) FROM updated",
                step_b,
            ),
        ):
            await assert_zero(query, parameter)
        for query, parameter in (
            (
                "WITH deleted AS (DELETE FROM sources WHERE id = $1 RETURNING 1) "
                "SELECT count(*) FROM deleted",
                source_b,
            ),
            (
                "WITH deleted AS (DELETE FROM users WHERE id = $1 RETURNING 1) "
                "SELECT count(*) FROM deleted",
                user_b,
            ),
            (
                "WITH deleted AS (DELETE FROM jobs WHERE id = $1 RETURNING 1) "
                "SELECT count(*) FROM deleted",
                job_b,
            ),
            (
                "WITH deleted AS (DELETE FROM job_steps WHERE id = $1 RETURNING 1) "
                "SELECT count(*) FROM deleted",
                step_b,
            ),
        ):
            await assert_zero(query, parameter)
        await assert_denied(
            "INSERT INTO tenants (id, kind, name) VALUES ($1, 'personal', 'forbidden')",
            uuid4(),
        )
        await assert_denied(
            "INSERT INTO users (id, tenant_id, oidc_subject, email) "
            "VALUES ($1, $2, 'synthetic-forbidden', 'forbidden@example.invalid')",
            uuid4(),
            tenant_b,
        )
        await assert_denied(
            "INSERT INTO memberships (id, tenant_id, user_id, role) VALUES ($1, $2, $3, 'student')",
            membership_b_extra,
            tenant_b,
            user_b_extra,
        )
        await assert_denied(
            "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key) "
            "VALUES ($1, $2, $3, 'ingest_source', $4)",
            uuid4(),
            tenant_b,
            source_b,
            f"forbidden-{uuid4()}",
        )
        await assert_denied(
            "INSERT INTO job_steps "
            "(id, tenant_id, job_id, entity_id, step, pipeline_version) "
            "VALUES ($1, $2, $3, $4, 'render_pages', 1)",
            uuid4(),
            tenant_b,
            job_b_probe,
            source_b,
        )
        await assert_denied(
            "INSERT INTO audit_log (tenant_id, action, target_type, target_id) "
            "VALUES ($1, 'rls.forbidden', 'source', $2)",
            tenant_b,
            str(uuid4()),
        )
        await assert_denied(
            "UPDATE audit_log SET action = 'forbidden' WHERE target_id = $1",
            str(audit_target_b),
        )
        for table in (
            "tenants",
            "users",
            "memberships",
            "sources",
            "jobs",
            "job_steps",
            "audit_log",
        ):
            assert await runtime.fetchval(f"SELECT count(*) FROM {table}") == 0

        async with runtime.transaction():
            await runtime.execute("SELECT set_config('app.tenant_id', 'not-a-uuid', true)")
            assert await runtime.fetchval("SELECT count(*) FROM sources") == 0
            assert await runtime.fetchval("SELECT count(*) FROM users") == 0

        async with runtime.transaction():
            await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_b))
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM tenants")} == {
                tenant_b
            }
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM users")} == {
                user_b,
                user_b_extra,
            }
            assert {
                row["user_id"] for row in await runtime.fetch("SELECT user_id FROM memberships")
            } == {user_b}
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM sources")} == {
                source_b,
                core_source,
            }
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM jobs")} == {
                job_b,
                job_b_probe,
            }
            assert {row["id"] for row in await runtime.fetch("SELECT id FROM job_steps")} == {
                step_b
            }
            assert {
                row["target_id"] for row in await runtime.fetch("SELECT target_id FROM audit_log")
            } == {str(audit_target_b)}
    finally:
        await runtime.close()
        await _cleanup(
            admin,
            [tenant_a, tenant_b],
            [source_a, source_b, core_source],
            [user_a, user_b, user_b_extra],
        )
        await admin.close()


def test_two_tenant_rls_against_runtime_role() -> None:
    required = {
        "RADBRAIN_RLS_ADMIN_DATABASE_URL",
        "RADBRAIN_RLS_RUNTIME_DATABASE_URL",
    }
    if not required.issubset(os.environ):
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("RLS proof requires disposable admin/runtime PostgreSQL URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run live RLS proof")
    asyncio.run(_assert_tenant_isolation())
