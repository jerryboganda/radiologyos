"""Opt-in live proof of knowledge depth against PostgreSQL (ADR 0030).

Runs as the RLS-bound runtime role with a scripted model transport (no
network): the three new tables are tenant-isolated; the depth pass classifies
a conflict, merges a near-duplicate concept reversibly, and writes a cited
note, and a re-run makes no model call; undo restores claims, edges and
aliases; "trust source B" supersedes A; table blocks become searchable rows.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks._knowledge_support import (  # noqa: E402
    ScriptedTransport,
    add_job,
    as_tenant,
    cleanup,
    require_env,
    seed,
)

# ($1 tenant, then the named references in order)
INSERTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "concept_notes": (
        "INSERT INTO concept_notes (tenant_id, user_id, concept_id, version, claims_hash, body, "
        "sentences, agent_version) VALUES ($1, $2, $3, (SELECT coalesce(max(version), 0) + 1 "
        "FROM concept_notes), repeat('a', 64), '{}'::jsonb, 1, 'concept_synthesis/v1')",
        ("tenant", "user", "k1"),
    ),
    "concept_merges": (
        "INSERT INTO concept_merges (tenant_id, user_id, concept_a, concept_b, similarity, "
        "decision, confidence, rationale, status, agent_version) VALUES ($1, $2, "
        "LEAST($3::uuid, $4::uuid), GREATEST($3::uuid, $4::uuid), 0.85, 'distinct', 0.9, 'r', "
        "'distinct', 'concept_resolver/v1')",
        ("tenant", "user", "k3", "k1"),
    ),
    "source_tables": (
        "INSERT INTO source_tables (tenant_id, source_id, page_no, block_no, bbox, n_rows, "
        "n_cols, cells, csv, html, plain) VALUES ($1, $2, 9, (SELECT count(*) FROM "
        "source_tables), '{0,0,1,1}', 1, 2, '[[\"a\",\"b\"]]', 'a,b', '<table></table>', 'a b')",
        ("tenant", "source"),
    ),
}
STATEMENTS = (
    ("k1", "Synthetic renal oncocytoma shows a central stellate scar on CT.", 5),
    ("k1", "Synthetic renal oncocytoma presents over 60 years in series one.", 3),
    ("k1", "Synthetic renal oncocytoma presents over 50 years in series two.", 3),
    ("k2", "Synthetic renal oncocytoma tumor shows a spoke-wheel pattern on angiography.", 4),
)


def _conflict(_prompt: str) -> dict[str, Any]:
    return {"label": "context", "confidence": 0.9, "cites": ["A", "B"],
            "rationale": "[A] and [B] describe different series.", "context": "series"}


def _resolver(_prompt: str) -> dict[str, Any]:
    return {"decision": "merge", "parent": "", "confidence": 0.95,
            "rationale": "Same entity; 'tumor' is redundant."}


def _synthesis(prompt: str) -> dict[str, Any]:
    pearls = [{"text": m.group(2), "cites": [m.group(1)]}
              for m in re.finditer(r"^\[(C\d+)\] \([^)]*\) (.+)$", prompt, re.M)]
    pearls.append({"text": "It metastasises in 40% of cases.", "cites": ["C1"]})
    return {"definition": [], "imaging": [], "differentials": [], "pearls": pearls,
            "pitfalls": []}


async def _seed_graph(runtime: Any, ids: dict[str, UUID]) -> dict[str, Any]:
    ta = ids["ta"]
    refs: dict[str, Any] = {"tenant": ta, "source": ids["sa"], "user": ids["ua"]}
    for key, name in (("k1", "Synthetic renal oncocytoma"),
                      ("k2", "Synthetic renal oncocytoma tumor"), ("k3", "Synthetic scar")):
        refs[key] = uuid4()
        await as_tenant(runtime, ta, "INSERT INTO concepts (id, tenant_id, name, normalized_name, "
                        "concept_type) VALUES ($1, $2, $3, lower($3), 'disease')",
                        refs[key], ta, name)
    claims = []
    for key, statement, importance in STATEMENTS:
        rows = await as_tenant(
            runtime, ta, "INSERT INTO claims (tenant_id, concept_id, statement, evidence_span, "
            "source_id, page_from, page_to, citation, importance, agent_version) VALUES "
            "($1, $2, $3, $3, $4, 1, 1, '{\"source_title\": \"Synthetic\", \"page_from\": 1, "
            "\"page_to\": 1}'::jsonb, $5, 'knowledge_extract/v1') RETURNING id",
            ta, refs[key], statement, ids["sa"], importance)
        claims.append(rows[0]["id"])
    refs["claims"] = claims
    await as_tenant(runtime, ta, "INSERT INTO knowledge_conflicts (tenant_id, concept_id, "
                    "claim_a, claim_b, kind, description) VALUES ($1, $2, $3, $4, 'numeric', "
                    "'Numeric disagreement (years)')", ta, refs["k1"], claims[1], claims[2])
    await as_tenant(runtime, ta, "UPDATE claims SET status = 'disputed' WHERE id = ANY($1)",
                    claims[1:3])
    await as_tenant(runtime, ta, "INSERT INTO concept_edges (tenant_id, from_concept, "
                    "to_concept, relation, source_id, citation, agent_version) VALUES ($1, $2, "
                    "$3, 'sign_of', $4, '{}'::jsonb, 'v1')", ta, refs["k2"], refs["k3"], ids["sa"])
    return refs


async def _table_proof(runtime: Any, ids: dict[str, UUID], refs: dict[str, Any]) -> None:
    for table, (sql, keys) in INSERTS.items():
        args = [refs.get(key, uuid4()) for key in keys]
        await as_tenant(runtime, ids["ta"], sql, *args)
        assert await as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}"), table
        assert await as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
        assert await as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await as_tenant(runtime, ids["tb"], sql, *args)
        assert await as_tenant(runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 "
                               "RETURNING 1", ids["tb"]) == [], table
        assert await as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1") == []
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await as_tenant(runtime, ids["tb"], INSERTS["concept_notes"][0],
                        ids["tb"], ids["ub"], refs["k1"])


async def _depth_proof(deps: Any, runtime: Any, ids: dict[str, UUID],
                       refs: dict[str, Any]) -> None:
    from apps.worker.app.knowledge.depth import run_depth

    ta = ids["ta"]
    assert await run_depth(deps, ta, ids["sa"], fresh=True) == "succeeded"
    assert deps.transport.calls == ["claim_conflict", "concept_resolver", "concept_synthesis"]
    [conflict] = await as_tenant(runtime, ta, "SELECT status, ai_label, trust "
                                 "FROM knowledge_conflicts")
    assert (conflict["status"], conflict["ai_label"], conflict["trust"]) == (
        "resolved", "context", None)
    [merge] = await as_tenant(runtime, ta, "SELECT id, status, survivor, merged "
                              "FROM concept_merges WHERE decision = 'merge'")
    assert (merge["status"], merge["survivor"], merge["merged"]) == (
        "applied", refs["k1"], refs["k2"])
    owners = {r["concept_id"] for r in await as_tenant(runtime, ta, "SELECT concept_id "
                                                       "FROM claims")}
    assert owners == {refs["k1"]}
    [edge] = await as_tenant(runtime, ta, "SELECT from_concept FROM concept_edges")
    assert edge["from_concept"] == refs["k1"]
    [note] = await as_tenant(runtime, ta, "SELECT status, sentences, dropped, claim_ids "
                             "FROM concept_notes WHERE concept_id = $1", refs["k1"])
    assert (note["status"], note["sentences"], note["dropped"]) == ("draft", 4, 1)
    assert set(note["claim_ids"]) == set(refs["claims"])
    assert await run_depth(deps, ta, ids["sa"], fresh=True) == "succeeded"
    assert len(deps.transport.calls) == 3  # every unit is already done
    refs["merge_id"] = merge["id"]


async def _undo_and_trust_proof(engine: Any, runtime: Any, ids: dict[str, UUID],
                                refs: dict[str, Any]) -> None:
    from apps.api.app.knowledge import merge_review, trust
    from apps.api.app.security.principal import Principal
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    ta, owner = ids["ta"], Principal(user_id=ids["ua"], tenant_id=ids["ta"])
    stranger = Principal(user_id=ids["ub"], tenant_id=ids["tb"])

    async def call(principal: Any, fn: Any, *args: Any) -> Any:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"),
                                  {"t": str(principal.tenant_id)})
            return await fn(session, principal, *args)

    assert await call(stranger, merge_review.undo, refs["merge_id"]) is None
    undone = await call(owner, merge_review.undo, refs["merge_id"])
    assert undone["status"] == "undone"
    [k2] = await as_tenant(runtime, ta, "SELECT merged_into FROM concepts WHERE id = $1",
                           refs["k2"])
    assert k2["merged_into"] is None
    [k1] = await as_tenant(runtime, ta, "SELECT aliases FROM concepts WHERE id = $1", refs["k1"])
    assert "Synthetic renal oncocytoma tumor" not in k1["aliases"]
    moved = await as_tenant(runtime, ta, "SELECT 1 FROM claims WHERE concept_id = $1",
                            refs["k2"])
    [edge] = await as_tenant(runtime, ta, "SELECT from_concept FROM concept_edges")
    assert len(moved) == 1 and edge["from_concept"] == refs["k2"]
    claims = refs["claims"]
    [row] = await as_tenant(runtime, ta, "INSERT INTO knowledge_conflicts (tenant_id, "
                            "concept_id, claim_a, claim_b, kind, description) VALUES ($1, $2, "
                            "$3, $4, 'negation', 'x') RETURNING id", ta, refs["k1"],
                            claims[0], claims[1])
    assert await call(stranger, trust.trust_conflict, row["id"], "b", "") is None
    trusted = await call(owner, trust.trust_conflict, row["id"], "b", "Newer edition")
    assert trusted["trust"] == "b" and trusted["preferred_claim"] == claims[1]
    statuses = {r["id"]: r["status"] for r in await as_tenant(
        runtime, ta, "SELECT id, status FROM claims WHERE id = ANY($1)", claims[:2])}
    assert statuses == {claims[0]: "superseded", claims[1]: "active"}


async def _tables_proof(engine: Any, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.library.tables import page_tables, search_tables
    from apps.worker.app.ingest.db import tenant_tx
    from apps.worker.app.ingest.tables import extract_tables

    ta = ids["ta"]
    await as_tenant(runtime, ta, "INSERT INTO source_blocks (tenant_id, source_id, page_no, "
                    "block_no, kind, text, bbox, origin) VALUES ($1, $2, 3, 0, 'table', "
                    "'Bosniak | Enhancement\nIIF | minimal septal', '{0.1,0.2,0.9,0.5}', "
                    "'vision')", ta, ids["sa"])
    async with tenant_tx(engine, ta) as session:
        assert await extract_tables(session, ta, ids["sa"]) == 1
        [table] = await page_tables(session, ids["sa"], 3)
        hits = await search_tables(session, ids["ua"], "septal enhancement")
        missed = await search_tables(session, ids["ub"], "septal enhancement")
    assert table["cells"] == [["Bosniak", "Enhancement"], ["IIF", "minimal septal"]]
    assert list(table["bbox"]) == pytest.approx([0.1, 0.2, 0.9, 0.5])
    assert [h["page_no"] for h in hits] == [3] and missed == []
    async with tenant_tx(engine, ids["tb"]) as session:
        assert await search_tables(session, ids["ua"], "septal enhancement") == []


async def _run() -> None:
    from apps.worker.app.knowledge.runtime import KnowledgeDeps
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await seed(admin)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    transport = ScriptedTransport({"claim_conflict": _conflict, "concept_resolver": _resolver,
                                   "concept_synthesis": _synthesis})
    try:
        await add_job(runtime, ids["ta"], ids["sa"])
        refs = await _seed_graph(runtime, ids)
        await _depth_proof(KnowledgeDeps(engine=engine, transport=transport), runtime, ids, refs)
        await _undo_and_trust_proof(engine, runtime, ids, refs)
        await _tables_proof(engine, runtime, ids)
        await _table_proof(runtime, ids, refs)
    finally:
        await engine.dispose()
        await runtime.close()
        await cleanup(admin, ids)
        await admin.close()


def test_knowledge_depth_against_runtime_role() -> None:
    require_env()
    asyncio.run(_run())
