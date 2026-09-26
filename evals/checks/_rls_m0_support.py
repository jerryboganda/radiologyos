"""Synthetic two-tenant fixture for the M0 tables of the live RLS proof.

Rows are written by the admin connection (which bypasses RLS) and removed in
``cleanup``; every value is synthetic and uses ``example.invalid`` addresses.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

CORE_TENANT_ID = "00000000-0000-0000-0000-000000000001"
M0_TABLES = ("tenants", "users", "memberships", "sources", "jobs", "job_steps", "audit_log")


def source_hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class M0Fixture:
    tenant_a: UUID = field(default_factory=uuid4)
    tenant_b: UUID = field(default_factory=uuid4)
    user_a: UUID = field(default_factory=uuid4)
    user_b: UUID = field(default_factory=uuid4)
    user_b_extra: UUID = field(default_factory=uuid4)
    source_a: UUID = field(default_factory=uuid4)
    source_b: UUID = field(default_factory=uuid4)
    core_source: UUID = field(default_factory=uuid4)
    job_a: UUID = field(default_factory=uuid4)
    job_b: UUID = field(default_factory=uuid4)
    job_b_probe: UUID = field(default_factory=uuid4)
    step_a: UUID = field(default_factory=uuid4)
    step_b: UUID = field(default_factory=uuid4)
    membership_b_extra: UUID = field(default_factory=uuid4)
    audit_target_a: UUID = field(default_factory=uuid4)
    audit_target_b: UUID = field(default_factory=uuid4)


async def _seed_identity(admin: Any, fx: M0Fixture) -> None:
    await admin.execute(
        "INSERT INTO tenants (id, kind, name) VALUES "
        "($1, 'personal', 'RLS Tenant A'), ($2, 'personal', 'RLS Tenant B')",
        fx.tenant_a,
        fx.tenant_b,
    )
    await admin.execute(
        "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES "
        "($1, $3, 'synthetic-rls-a', 'a@example.invalid'), "
        "($2, $4, 'synthetic-rls-b', 'b@example.invalid'), "
        "($5, $4, 'synthetic-rls-b-extra', 'b-extra@example.invalid')",
        fx.user_a,
        fx.user_b,
        fx.tenant_a,
        fx.tenant_b,
        fx.user_b_extra,
    )
    await admin.execute(
        "INSERT INTO memberships (tenant_id, user_id, role) VALUES "
        "($1, $2, 'student'), ($3, $4, 'student')",
        fx.tenant_a,
        fx.user_a,
        fx.tenant_b,
        fx.user_b,
    )


async def _seed_sources(admin: Any, fx: M0Fixture) -> None:
    await admin.execute(
        "INSERT INTO sources "
        "(id, tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
        "title, status, rights_status) VALUES "
        "($1, $2, $3, 'note', 'private', $4, $5, 'Tenant A', 'ready', 'unverified'), "
        "($6, $7, $8, 'note', 'private', $9, $10, 'Tenant B', 'ready', 'unverified'), "
        "($11, $12, NULL, 'note', 'core', $13, NULL, 'Reviewed Core', 'ready', 'licensed')",
        fx.source_a,
        fx.tenant_a,
        fx.user_a,
        source_hash("a"),
        f"tenants/{fx.tenant_a}/synthetic-a",
        fx.source_b,
        fx.tenant_b,
        fx.user_b,
        source_hash("b"),
        f"tenants/{fx.tenant_b}/synthetic-b",
        fx.core_source,
        CORE_TENANT_ID,
        source_hash("core"),
    )


async def _seed_jobs(admin: Any, fx: M0Fixture) -> None:
    await admin.execute(
        "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key) VALUES "
        "($1, $2, $3, 'ingest_source', $4), "
        "($5, $6, $7, 'ingest_source', $8), "
        "($9, $6, $7, 'ingest_source', $10)",
        fx.job_a,
        fx.tenant_a,
        fx.source_a,
        f"rls-job-{fx.job_a}",
        fx.job_b,
        fx.tenant_b,
        fx.source_b,
        f"rls-job-{fx.job_b}",
        fx.job_b_probe,
        f"rls-job-{fx.job_b_probe}",
    )
    await admin.execute(
        "INSERT INTO job_steps "
        "(id, tenant_id, job_id, entity_id, step, pipeline_version, status) VALUES "
        "($1, $2, $3, $4, 'upload_dedupe_scan', 1, 'succeeded'), "
        "($5, $6, $7, $8, 'upload_dedupe_scan', 1, 'succeeded')",
        fx.step_a,
        fx.tenant_a,
        fx.job_a,
        fx.source_a,
        fx.step_b,
        fx.tenant_b,
        fx.job_b,
        fx.source_b,
    )
    await admin.execute(
        "INSERT INTO audit_log (tenant_id, action, target_type, target_id) VALUES "
        "($1, 'rls.read', 'source', $2), ($3, 'rls.read', 'source', $4)",
        fx.tenant_a,
        str(fx.audit_target_a),
        fx.tenant_b,
        str(fx.audit_target_b),
    )


async def seed(admin: Any, fx: M0Fixture) -> None:
    async with admin.transaction():
        await _seed_identity(admin, fx)
        await _seed_sources(admin, fx)
        await _seed_jobs(admin, fx)


async def cleanup(admin: Any, fx: M0Fixture) -> None:
    tenants = [fx.tenant_a, fx.tenant_b]
    sources = [fx.source_a, fx.source_b, fx.core_source]
    users = [fx.user_a, fx.user_b, fx.user_b_extra]
    async with admin.transaction():
        for table in ("audit_log", "job_steps", "jobs"):
            await admin.execute(
                f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",  # nosec B608
                tenants,
            )
        await admin.execute("DELETE FROM sources WHERE id = ANY($1::uuid[])", sources)
        await admin.execute("DELETE FROM memberships WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", users)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)
