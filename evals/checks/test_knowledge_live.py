"""Opt-in live RLS proof for the knowledge tables (migration 0008, ADR 0016).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role. For
every new tenant table: tenant B cannot see, move, or delete tenant A's rows,
cannot write rows carrying tenant A's id, nothing is visible without tenant
context, and composite foreign keys refuse cross-tenant references.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks._knowledge_support import (  # noqa: E402
    add_job,
    as_tenant,
    cleanup,
    require_env,
    seed,
)

# Each insert takes ($1 tenant, $2 source, $3 user, $4 concept, $5 concept2, $6 claim,
# $7 claim2, $8 fresh id) and uses the arguments it needs, in that order.
INSERTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "concepts": (
        "INSERT INTO concepts (id, tenant_id, name, normalized_name) "
        "VALUES ($2, $1, 'Rls concept', 'rls concept ' || $2::text)",
        ("tenant", "fresh"),
    ),
    "claims": (
        "INSERT INTO claims (tenant_id, concept_id, statement, evidence_span, source_id, "
        "page_from, page_to, citation, agent_version) "
        "VALUES ($1, $2, 'claim', 'span text', $3, 1, 1, '{}'::jsonb, 'knowledge_extract/v1')",
        ("tenant", "concept", "source"),
    ),
    "concept_edges": (
        "INSERT INTO concept_edges (tenant_id, from_concept, to_concept, relation, source_id, "
        "citation, agent_version) VALUES ($1, $2, $3, 'sign_of', $4, '{}'::jsonb, 'v1')",
        ("tenant", "concept", "concept2", "source"),
    ),
    "knowledge_conflicts": (
        "INSERT INTO knowledge_conflicts (tenant_id, concept_id, claim_a, claim_b, kind, "
        "description) VALUES ($1, $2, $3, $4, 'numeric', 'synthetic')",
        ("tenant", "concept", "claim", "claim2"),
    ),
    "curriculum_mappings": (
        "INSERT INTO curriculum_mappings (tenant_id, source_id, unit_hash, page_from, page_to, "
        "curriculum_code, topic, confidence, status, agent_version) "
        "VALUES ($1, $2, 'abcdef0123456789', 1, 1, 'CHEST', 'x', 0.9, 'accepted', 'v1')",
        ("tenant", "source"),
    ),
    "topic_frequencies": (
        "INSERT INTO topic_frequencies (tenant_id, user_id, source_id, page_no, exam_target, "
        "curriculum_code, topic, count, agent_version) "
        "VALUES ($1, $2, $3, 1, 'imm', 'CHEST', 'x', 1, 'v1')",
        ("tenant", "user", "source"),
    ),
    "topic_weights": (
        "INSERT INTO topic_weights (tenant_id, user_id, exam_target, curriculum_code, weight, "
        "basis) VALUES ($1, $2, 'imm', 'CHEST', 0.5, '{}'::jsonb)",
        ("tenant", "user"),
    ),
    "knowledge_runs": (
        "INSERT INTO knowledge_runs (tenant_id, source_id, unit, agent_version, "
        "pipeline_version, status) VALUES ($1, $2, 'chunk:abc', 'v1', 1, 'succeeded')",
        ("tenant", "source"),
    ),
}


async def _prerequisites(runtime: Any, ids: dict[str, UUID]) -> dict[str, UUID]:
    refs = {"tenant": ids["ta"], "source": ids["sa"], "user": ids["ua"]}
    for key in ("concept", "concept2"):
        refs[key] = uuid4()
        await as_tenant(runtime, ids["ta"], INSERTS["concepts"][0], ids["ta"], refs[key])
    for key in ("claim", "claim2"):
        rows = await as_tenant(
            runtime, ids["ta"], INSERTS["claims"][0] + " RETURNING id",
            ids["ta"], refs["concept"], ids["sa"])
        refs[key] = rows[0]["id"]
    return refs


async def _table_proof(runtime: Any, ids: dict[str, UUID], refs: dict[str, UUID]) -> None:
    for table, (sql, keys) in INSERTS.items():
        args = [refs.get(key, uuid4()) for key in keys]
        before = len(await as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}"))
        await as_tenant(runtime, ids["ta"], sql, *args)
        visible = await as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}")
        assert len(visible) == before + 1, table
        assert await as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
        assert await as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await as_tenant(runtime, ids["tb"], sql, *[refs.get(k, uuid4()) for k in keys])
        moved = await as_tenant(
            runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 RETURNING 1", ids["tb"])
        assert moved == [], table
        deleted = await as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1")
        assert deleted == [], table


async def _cross_tenant_references(runtime: Any, ids: dict[str, UUID],
                                   refs: dict[str, UUID]) -> None:
    """Tenant B cannot attach its rows to tenant A's concept (composite FK)."""
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await as_tenant(runtime, ids["tb"], INSERTS["claims"][0],
                        ids["tb"], refs["concept"], ids["sb"])


async def _run() -> None:
    admin_dsn, runtime_dsn = require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await seed(admin)
    try:
        await add_job(runtime, ids["ta"], ids["sa"])
        refs = await _prerequisites(runtime, ids)
        await _table_proof(runtime, ids, refs)
        await _cross_tenant_references(runtime, ids, refs)
    finally:
        await runtime.close()
        await cleanup(admin, ids)
        await admin.close()


def test_knowledge_tables_enforce_tenant_isolation_as_runtime_role() -> None:
    require_env()
    asyncio.run(_run())
