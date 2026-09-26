"""Shared seeding, cleanup and fake model transport for the knowledge live proofs."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from packages.library import storage
from packages.models.claude_code import ModelCall, ModelResult
from packages.models.gateway import load_agent

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
KNOWLEDGE_TABLES = (
    "model_escalations", "ops_alerts",
    "concept_notes", "concept_merges", "knowledge_conflicts", "concept_edges", "claims",
    "curriculum_mappings", "topic_frequencies", "topic_weights", "knowledge_runs", "concepts",
)
LIBRARY_TABLES = ("source_tables", "chunks", "figures", "source_blocks", "source_pages",
                  "job_steps", "jobs", "audit_log", "sources")


def require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("knowledge live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the knowledge proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "sb", "sp")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Know A'),"
            "($2,'personal','Know B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"know-{ids[user]}", f"{ids[user]}@example.invalid")
        for source, tenant, user in (("sa", "ta", "ua"), ("sb", "tb", "ub"), ("sp", "ta", "ua")):
            await admin.execute(
                "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, "
                "storage_key, title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic')",
                ids[source], ids[tenant], ids[user], uuid4().hex + uuid4().hex,
                storage.original_key(ids[tenant], ids[source], "pdf"))
    return ids


async def cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in (*KNOWLEDGE_TABLES, *LIBRARY_TABLES):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def add_job(runtime: Any, tenant: UUID, source: UUID) -> UUID:
    job = uuid4()
    await as_tenant(
        runtime, tenant,
        "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key) "
        "VALUES ($1,$2,$3,'ingest_source',$4)", job, tenant, source, f"ingest:{job}")
    return job


class ScriptedTransport:
    """Fake model transport: picks a scripted output by agent and user prompt."""

    def __init__(self, scripts: dict[str, Callable[[str], dict[str, Any]]]) -> None:
        self.by_prompt = {load_agent(name).prompt.system_prompt: (name, fn)
                          for name, fn in scripts.items()}
        self.calls: list[str] = []

    def run(self, call: ModelCall) -> ModelResult:
        name, script = self.by_prompt[call.system_prompt]
        self.calls.append(name)
        return ModelResult(output=script(call.user_prompt), duration_ms=1, cost_usd=0.0)
