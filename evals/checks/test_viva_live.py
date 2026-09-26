"""Opt-in live proof for viva sessions and staged image cases (migration 0018).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* ``viva_sessions`` and ``viva_turns`` hide tenant A's rows from tenant B,
  reject writes with a foreign tenant_id, show nothing without tenant context,
  and a turn cannot attach to another tenant's session;
* a viva opens, grades an answer, escalates, and ends through the worker step
  (fake transport); a duplicate step is a no-op and tenant B's step finds nothing;
* a staged case writes its rubric, stores a checked bank question, grades all
  five stages, finishes, and records one attempt for that question.
All content is synthetic.
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
CHUNK_TEXT = "Crazy paving is classic for pulmonary alveolar proteinosis."
STAGES = ("describe", "findings", "diagnosis", "differentials", "next_step")
CHECK = {"single_best_answer": True, "key_supported": True, "no_cueing": True,
         "distractors_plausible": True, "difficulty_agrees": True, "verdict": "pass",
         "reasons": []}


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("viva proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the viva proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


def _question(cite: str) -> dict[str, Any]:
    return {"question": "What pattern is shown?", "hint": "",
            "expected_points": [{"point": "crazy paving", "citations": [cite]}]}


OUTPUTS: dict[str, Any] = {
    "viva_open": {"topic": "PAP", "scenario": "Look at this HRCT.", "citations": ["F1"],
                  "question": _question("E1")},
    "viva_examiner": {
        "points": [{"index": 0, "status": "matched", "justification": "named it"}],
        "reasoning": 3, "communication": 3, "unsafe": False, "feedback": "Good.",
        "teaching_point": {"text": "Crazy paving suggests PAP.", "citations": ["E1"]},
        "escalate": _question("E1"), "probe": _question("E1")},
    "image_case_stages": {
        "topic": "PAP", "stem": "Look at this image.", "citations": ["F1"],
        "stages": [{"stage": s, "model_answer": f"{s} answer",
                    "points": [{"point": f"{s} point", "marks": 2, "citations": ["E1"]}]}
                   for s in STAGES]},
    "question_check": CHECK,
    "seq_grade": {"points": [{"scheme_index": 0, "status": "matched", "awarded": 2,
                              "justification": "j"}], "feedback": "Fine."},
}


class FakeTransport:
    """Answers each agent with a fixed synthetic output, matched by output schema."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def run(self, call: Any) -> Any:
        from packages.models.claude_code import ModelResult
        from packages.models.gateway import load_agent

        name = next(n for n in OUTPUTS if load_agent(n).schema == call.output_schema)
        self.calls.append(name)
        return ModelResult(output=OUTPUTS[name], duration_ms=1, cost_usd=0.0)


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Viva A'),"
            "($2,'personal','Viva B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"viva-{ids[user]}", f"{ids[user]}@example.invalid")
        await admin.execute(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, title) "
            "VALUES ($1,$2,$3,'pdf','private',$4,'Synthetic chest')",
            ids["sa"], ids["ta"], ids["ua"], uuid4().hex + uuid4().hex)
        ids["chunk"] = await admin.fetchval(
            "INSERT INTO chunks (tenant_id, source_id, chunk_no, page_from, page_to, text) "
            "VALUES ($1,$2,0,2,2,$3) RETURNING id", ids["ta"], ids["sa"], CHUNK_TEXT)
        ids["figure"] = await admin.fetchval(
            "INSERT INTO figures (tenant_id, source_id, page_no, figure_no, bbox, caption, "
            "description, modality) VALUES ($1,$2,2,0,'{0,0,1,1}','Figure 1',"
            "'Geographic ground-glass with septal thickening','CT') RETURNING id",
            ids["ta"], ids["sa"])
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("viva_turns", "viva_sessions", "attempts", "questions", "chunks",
                      "figures", "sources", "users"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


SESSION_SQL = ("INSERT INTO viva_sessions (tenant_id, user_id, kind) VALUES ($1,$2,'viva') "
               "RETURNING id")
TURN_SQL = ("INSERT INTO viva_turns (tenant_id, user_id, session_id, turn_no, level, move, "
            "prompt, expected) VALUES ($1,$2,$3,1,1,'open','Q','[{\"point\":\"p\"}]')")


async def _rls_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb, ua, ub = ids["ta"], ids["tb"], ids["ua"], ids["ub"]
    sid = (await _as_tenant(runtime, ta, SESSION_SQL, ta, ua))[0][0]
    await _as_tenant(runtime, ta, TURN_SQL, ta, ua, sid)
    for table in ("viva_sessions", "viva_turns"):
        assert await _as_tenant(runtime, tb, f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ta, f"SELECT 1 FROM {table}")) == 1, table
        moved = await _as_tenant(runtime, tb, f"UPDATE {table} SET tenant_id = $1 RETURNING 1", tb)
        assert moved == [], table
        assert await _as_tenant(runtime, tb, f"DELETE FROM {table} RETURNING 1") == [], table
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, SESSION_SQL, ta, ua)
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await _as_tenant(runtime, tb, TURN_SQL, tb, ub, sid)
    await _as_tenant(runtime, ta, "DELETE FROM viva_sessions")
    assert await _as_tenant(runtime, ta, "SELECT 1 FROM viva_turns") == []


def _evidence(ids: dict[str, UUID]) -> list[dict[str, Any]]:
    common = {"source_id": str(ids["sa"]), "source_title": "Synthetic chest"}
    return [
        {"ref": "F1", "heading": "Figure 1", "citation": {
            "kind": "figure", "figure_id": str(ids["figure"]), "page_no": 2, **common}},
        {"ref": "E1", "heading": "", "citation": {
            "kind": "chunk", "chunk_id": str(ids["chunk"]), "page_from": 2, "page_to": 2,
            **common}},
    ]


async def _new_session(engine: Any, ids: dict[str, UUID], kind: str) -> UUID:
    from apps.api.app.assessment import viva_store
    from apps.api.app.core.time import now_utc
    from apps.worker.app.ingest.db import tenant_tx

    async with tenant_tx(engine, ids["ta"]) as db:
        return await viva_store.insert_session(db, ids["ta"], ids["ua"], {
            "kind": kind, "style": "fcps2_toacs", "topic": "PAP", "figure_id": ids["figure"],
            "evidence": _evidence(ids), "status": "preparing", "work": "pending",
            "max_turns": 6, "started_at": now_utc()})


async def _answer(engine: Any, ids: dict[str, UUID], sid: UUID, turn_no: int) -> None:
    from apps.api.app.assessment import viva_service
    from apps.api.app.core.time import now_utc
    from apps.api.app.security.principal import Principal
    from apps.worker.app.ingest.db import tenant_tx

    principal = Principal(user_id=ids["ua"], tenant_id=ids["ta"])
    async with tenant_tx(engine, ids["ta"]) as db:
        assert await viva_service.submit_answer(db, principal, sid, turn_no, "crazy paving",
                                                now_utc())


async def _viva_flow(engine: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import viva_service, viva_store
    from apps.api.app.core.time import now_utc
    from apps.api.app.security.principal import Principal
    from apps.worker.app.assessment.viva import run_viva_step
    from apps.worker.app.ingest.db import tenant_tx

    fake = FakeTransport()
    sid = await _new_session(engine, ids, "viva")
    assert await run_viva_step(engine, fake, ids["tb"], sid, 0) == "missing"
    assert await run_viva_step(engine, fake, ids["ta"], sid, 0) == "applied"
    assert await run_viva_step(engine, fake, ids["ta"], sid, 0) == "done"
    await _answer(engine, ids, sid, 1)
    assert await run_viva_step(engine, fake, ids["ta"], sid, 1) == "applied"
    assert fake.calls == ["viva_open", "viva_examiner"]
    principal = Principal(user_id=ids["ua"], tenant_id=ids["ta"])
    async with tenant_tx(engine, ids["ta"]) as db:
        turns = await viva_store.load_turns(db, sid)
        assert [(t["turn_no"], t["status"], t["level"]) for t in turns] == [
            (1, "graded", 1), (2, "asked", 2)]
        await viva_service.end_session(db, principal, sid, now_utc())
        row = await viva_store.load_session(db, ids["ua"], sid)
    assert row is not None and row["status"] == "finished"
    assert row["debrief"]["teaching_points"][0]["citations"][0]["ref"] == "E1"
    async with tenant_tx(engine, ids["tb"]) as db:
        assert await viva_store.load_session(db, None, sid) is None


async def _staged_flow(engine: Any, admin: Any, ids: dict[str, UUID]) -> None:
    from apps.api.app.assessment import viva_store
    from apps.worker.app.assessment.viva import run_viva_step
    from apps.worker.app.ingest.db import tenant_tx

    fake = FakeTransport()
    sid = await _new_session(engine, ids, "image_case")
    assert await run_viva_step(engine, fake, ids["ta"], sid, 0) == "applied"
    for turn_no in range(1, 6):
        await _answer(engine, ids, sid, turn_no)
        assert await run_viva_step(engine, fake, ids["ta"], sid, turn_no) == "applied"
    async with tenant_tx(engine, ids["ta"]) as db:
        row = await viva_store.load_session(db, ids["ua"], sid)
    assert row is not None and row["stop_reason"] == "stages_complete"
    assert [s["stage"] for s in row["debrief"]["stages"]] == list(STAGES)
    assert row["debrief"]["overall_percent"] == 100.0
    stored = await _as_tenant(admin, None, "SELECT status, answer FROM questions WHERE id = $1",
                              row["question_id"])
    assert stored[0]["status"] == "active"
    attempts = await _as_tenant(admin, None, "SELECT score, max_score FROM attempts "
                                "WHERE question_id = $1", row["question_id"])
    assert [(float(a[0]), float(a[1])) for a in attempts] == [(10.0, 10.0)]


async def _run() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        await _rls_proof(runtime, ids)
        await _viva_flow(engine, ids)
        await _staged_flow(engine, admin, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_viva_sessions_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
