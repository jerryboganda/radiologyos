"""Opt-in live proof for the tutor tables (migration 0005, ADR 0013).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* tutor_threads and tutor_messages hide tenant A's rows from tenant B, reject
  writes with a foreign tenant_id, and show nothing without tenant context;
* a message cannot attach to another tenant's thread (composite foreign key);
* the real repository stores a grounded exchange that only its owner can list
  and read, and retrieval + orchestration (fake transport) cite a real chunk.
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
THREAD_SQL = ("INSERT INTO tutor_threads (id, tenant_id, user_id, title) "
              "VALUES ($1,$2,$3,'Synthetic thread')")
MESSAGE_SQL = ("INSERT INTO tutor_messages (tenant_id, thread_id, role, content) "
               "VALUES ($1,$2,'user','Synthetic question')")


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("tutor live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the tutor proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "tha")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Tutor A'),"
            "($2,'personal','Tutor B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"tutor-{ids[user]}", f"{ids[user]}@example.invalid")
        await admin.execute(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, "
            "storage_key, title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic deck')",
            ids["sa"], ids["ta"], ids["ua"], uuid4().hex + uuid4().hex,
            f"tenants/{ids['ta']}/sources/{ids['sa']}/original.pdf")
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("tutor_messages", "tutor_threads", "chunks", "sources"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _isolated(runtime: Any, ids: dict[str, UUID], table: str) -> None:
    assert await _as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
    assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
    assert len(await _as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}")) >= 1, table
    moved = await _as_tenant(
        runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 RETURNING 1", ids["tb"])
    assert moved == [], table
    assert await _as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1") == [], table


async def _rls_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    await _as_tenant(runtime, ids["ta"], THREAD_SQL, ids["tha"], ids["ta"], ids["ua"])
    await _as_tenant(runtime, ids["ta"], MESSAGE_SQL, ids["ta"], ids["tha"])
    for table in ("tutor_threads", "tutor_messages"):
        await _isolated(runtime, ids, table)
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, ids["tb"], THREAD_SQL, uuid4(), ids["ta"], ids["ua"])
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, ids["tb"], MESSAGE_SQL, ids["ta"], ids["tha"])
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await _as_tenant(runtime, ids["tb"], MESSAGE_SQL, ids["tb"], ids["tha"])
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(
            runtime, ids["ta"], "INSERT INTO tutor_messages (tenant_id, thread_id, role, "
            "content) VALUES ($1,$2,'assistant','uncited')", ids["ta"], ids["tha"])
    await _as_tenant(runtime, ids["ta"], "DELETE FROM tutor_threads")


class _Transport:
    def run(self, call: Any) -> Any:
        from packages.models.claude_code import ModelResult

        output: dict[str, Any] = {
            "coverage": "full",
            "segments": [{"text": "PAP shows crazy paving.", "sources": ["S1"]}]}
        if "verdicts" in call.output_schema.get("properties", {}):  # grounding_judge
            output = {"verdicts": [{"segment": 1, "verdict": "supported", "reason": "S1."}]}
        return ModelResult(output=output, duration_ms=1, cost_usd=0.0)


async def _repo_proof(runtime_dsn: str, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.api.tutor import lexical_query
    from apps.api.app.library.search import hybrid_search
    from apps.api.app.tutor import repo
    from apps.worker.app.ingest.db import tenant_tx
    from packages.tutor.grounding import excerpts_from_hits
    from packages.tutor.orchestrator import answer_question
    from sqlalchemy.ext.asyncio import create_async_engine

    await _as_tenant(
        runtime, ids["ta"], "INSERT INTO chunks (tenant_id, source_id, chunk_no, page_from, "
        "page_to, text) VALUES ($1,$2,0,3,3,'Pulmonary alveolar proteinosis: crazy paving')",
        ids["ta"], ids["sa"])
    question = "What is the HRCT sign of alveolar proteinosis?"
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        async with tenant_tx(engine, ids["ta"]) as session:
            hits = await hybrid_search(session, ids["ua"], lexical_query(question), None, 8)
        answer = answer_question(_Transport(), question, excerpts_from_hits(hits), [], False)
        assert answer.grounding == "sources"
        assert answer.segments[0].citations[0].chunk_id == hits[0]["id"]
        async with tenant_tx(engine, ids["ta"]) as session:
            thread = await repo.create_thread(session, ids["ta"], ids["ua"], "Synthetic")
            await repo.add_exchange(session, ids["ta"], thread, question, answer)
        async with tenant_tx(engine, ids["ta"]) as session:
            listed = await repo.list_threads(session, ids["ua"])
            stored = await repo.thread_messages(session, thread)
            history = await repo.recent_history(session, thread)
        async with tenant_tx(engine, ids["tb"]) as session:
            assert await repo.list_threads(session, ids["ub"]) == []
            assert await repo.get_thread(session, ids["ub"], thread) is None
            assert await repo.thread_messages(session, thread) == []
    finally:
        await engine.dispose()
    assert [t["message_count"] for t in listed] == [2]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["grounding"] == "sources"
    assert stored[1]["citations"][0]["citations"]
    assert stored[1]["citations"][-1]["kind"] == "judge_stats"
    assert stored[1]["citations"][-1]["judge"]["supported"] == 1
    assert [t.role for t in history] == ["user", "assistant"]


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _rls_proof(runtime, ids)
        await _repo_proof(runtime_dsn, runtime, ids)
    finally:
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_tutor_tables_and_repository_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
