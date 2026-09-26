"""Opt-in live proof for migration 0010 (study depth) as the RLS-bound runtime role.

* baseline_tests and weekly_reports hide tenant A's rows from tenant B, reject
  writes carrying a foreign tenant_id, and show nothing without tenant context;
* app.weekly_reports_due and app.study_replans_due return (tenant_id, user_id)
  only, honour local time, skip finished work, and survive an unknown time zone;
* the real services resolve a question's system from its cited chunk, use
  approved weights, run a baseline through the exam engine, and store a weekly
  report and tomorrow's plan, while tenant B sees none of it.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from packages.library import storage  # noqa: E402

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
QUESTIONS = 8
TABLES = ("weekly_reports", "baseline_tests")
CLEANUP = ("weekly_reports", "baseline_tests", "attempts", "exams", "questions",
           "curriculum_mappings", "topic_weights", "study_plans", "study_profiles", "chunks",
           "audit_log", "sources")


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("study depth live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run this proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


def _option() -> dict[str, Any]:
    return {"text": "Option", "explanation": "Because.", "citations": []}


async def _seed_people(admin: Any, ids: dict[str, Any]) -> None:
    await admin.execute("INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Depth A'),"
                        "($2,'personal','Depth B')", ids["ta"], ids["tb"])
    for user, tenant in (("ua", "ta"), ("ub", "tb")):
        await admin.execute(
            "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
            ids[user], ids[tenant], f"depth-{ids[user]}", f"{ids[user]}@example.invalid")
    exam_date = datetime.now(UTC).date() + timedelta(days=100)
    for user, tenant, zone in (("ua", "ta", "UTC"), ("ub", "tb", "Not/AZone")):
        await admin.execute(
            "INSERT INTO study_profiles (tenant_id, user_id, exam_date, exam_targets, timezone, "
            "created_at) VALUES ($1,$2,$3,ARRAY['fcps2_theory'],$4, now() - interval '30 days')",
            ids[tenant], ids[user], exam_date, zone)


async def _seed_library(admin: Any, ids: dict[str, Any]) -> None:
    await admin.execute(
        "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
        "title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic')",
        ids["sa"], ids["ta"], ids["ua"], uuid4().hex + uuid4().hex,
        storage.original_key(ids["ta"], ids["sa"], "pdf"))
    await admin.execute(
        "INSERT INTO chunks (id, tenant_id, source_id, chunk_no, page_from, page_to, heading, "
        "text, block_refs) VALUES ($1,$2,$3,0,1,1,'PAP','Crazy paving on HRCT.','[]')",
        ids["ca"], ids["ta"], ids["sa"])
    await admin.execute(
        "INSERT INTO curriculum_mappings (tenant_id, source_id, unit_hash, chunk_id, page_from, "
        "page_to, curriculum_code, confidence, status, agent_version) "
        "VALUES ($1,$2,'abcdef0123456789',$3,1,1,'CHEST',0.9,'accepted','v1')",
        ids["ta"], ids["sa"], ids["ca"])
    citation = json.dumps([{"ref": "E1", "kind": "chunk", "chunk_id": str(ids["ca"])}])
    options = json.dumps([_option() for _ in range(5)])
    for qid in ids["questions"]:
        await admin.execute(
            "INSERT INTO questions (id, tenant_id, user_id, type, stem, options, answer, "
            "citations, status, agent_version) VALUES ($1,$2,$3,'sba','Stem?',$4::jsonb,"
            "'{\"key\": 0}'::jsonb,$5::jsonb,'active','v1')",
            qid, ids["ta"], ids["ua"], options, citation)
    await admin.execute(
        "INSERT INTO attempts (tenant_id, user_id, question_id, response, score, max_score, "
        "graded_by, created_at) VALUES ($1,$2,$3,'{}'::jsonb,1,1,'rule',now() - interval '1 day')",
        ids["ta"], ids["ua"], ids["questions"][0])
    await admin.execute(
        "INSERT INTO topic_weights (tenant_id, user_id, exam_target, curriculum_code, weight, "
        "basis, approved, approved_by, approved_at) "
        "VALUES ($1,$2,'fcps2_theory','CHEST',0.6,'{}'::jsonb,true,$2,now())",
        ids["ta"], ids["ua"])
    await admin.execute(
        "INSERT INTO exams (id, tenant_id, user_id, mode, question_ids) "
        "VALUES ($1,$2,$3,'practice',ARRAY[$4]::uuid[])",
        ids["ea"], ids["ta"], ids["ua"], ids["questions"][0])


async def _seed(admin: Any) -> dict[str, Any]:
    ids: dict[str, Any] = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "ca", "ea")}
    ids["questions"] = [uuid4() for _ in range(QUESTIONS)]
    async with admin.transaction():
        await _seed_people(admin, ids)
        await _seed_library(admin, ids)
    return ids


async def _cleanup(admin: Any, ids: dict[str, Any]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in CLEANUP:
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


def _inserts(ids: dict[str, Any]) -> dict[str, tuple[str, tuple[Any, ...]]]:
    ta, ua = ids["ta"], ids["ua"]
    return {
        "baseline_tests": ("INSERT INTO baseline_tests (tenant_id, user_id, exam_id, "
                           "question_ids, systems) VALUES ($1,$2,$3,ARRAY[$4]::uuid[],'{}')",
                           (ta, ua, ids["ea"], ids["questions"][0])),
        "weekly_reports": ("INSERT INTO weekly_reports (tenant_id, user_id, week_start, "
                           "report_version, report) VALUES ($1,$2,$3,1,'{}')",
                           (ta, ua, date(2026, 9, 14))),
    }


async def _rls_proof(runtime: Any, ids: dict[str, Any]) -> None:
    for table, (sql, args) in _inserts(ids).items():
        await _as_tenant(runtime, ids["ta"], sql, *args)
        assert await _as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}")) == 1, table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, ids["tb"], sql, *args)
        moved = await _as_tenant(
            runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 RETURNING 1", ids["tb"])
        assert moved == [], table
        assert await _as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1") == []
        await _as_tenant(runtime, ids["ta"], f"DELETE FROM {table}")


async def _pairs(runtime: Any, sql: str, *args: Any) -> set[tuple[UUID, UUID]]:
    rows = await runtime.fetch(sql, *args)
    for row in rows:
        assert set(row.keys()) == {"tenant_id", "user_id"}  # ids only, never content
    return {(row["tenant_id"], row["user_id"]) for row in rows}


async def _resolver_proof(runtime: Any, ids: dict[str, Any]) -> None:
    mine, theirs = (ids["ta"], ids["ua"]), (ids["tb"], ids["ub"])
    today = datetime.now(UTC).date()
    monday = today + timedelta(days=7 - today.weekday())
    weekly = "SELECT * FROM app.weekly_reports_due($1)"
    due = await _pairs(runtime, weekly, datetime.combine(monday, time(7, 0), UTC))
    assert mine in due and theirs not in due
    assert mine not in await _pairs(runtime, weekly, datetime.combine(monday, time(5), UTC))
    await _as_tenant(runtime, ids["ta"],
                     "INSERT INTO weekly_reports (tenant_id, user_id, week_start, "
                     "report_version, report) VALUES ($1,$2,$3,1,'{}')",
                     ids["ta"], ids["ua"], monday - timedelta(days=7))
    assert mine not in await _pairs(runtime, weekly, datetime.combine(monday, time(7), UTC))
    replan = "SELECT * FROM app.study_replans_due($1, $2)"
    late = datetime.combine(today, time(23, 0), UTC)
    assert mine in await _pairs(runtime, replan, late, 2)
    assert mine not in await _pairs(runtime, replan, late - timedelta(hours=3), 2)
    await _as_tenant(runtime, ids["ta"],
                     "INSERT INTO study_plans (tenant_id, user_id, plan_date, phase, "
                     "days_remaining, minutes, plan_version, blocks) "
                     "VALUES ($1,$2,$3,'coverage',99,60,2,'[]')",
                     ids["ta"], ids["ua"], today + timedelta(days=1))
    assert mine not in await _pairs(runtime, replan, late, 2)
    assert mine in await _pairs(runtime, replan, late, 3)
    for table in ("weekly_reports", "study_plans"):
        await _as_tenant(runtime, ids["ta"], f"DELETE FROM {table}")


@asynccontextmanager
async def _repo(engine: Any, tenant: UUID) -> AsyncIterator[Any]:
    from apps.api.app.study.repo import SqlStudyRepo
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"),
                              {"t": str(tenant)})
        yield SqlStudyRepo(session, tenant)


async def _baseline_proof(engine: Any, ids: dict[str, Any], now: datetime) -> None:
    from apps.api.app.assessment import exams
    from apps.api.app.study import baseline

    async with _repo(engine, ids["ta"]) as repo:
        view, created = await baseline.start(repo, ids["ua"], now, seed=1)
    assert created and view["question_count"] == QUESTIONS and view["systems"] == ["CHEST"]
    async with _repo(engine, ids["ta"]) as repo:
        await exams.submit(repo.session, ids["ta"], ids["ua"], view["exam_id"])
        await repo.commit()
    async with _repo(engine, ids["ta"]) as repo:
        done = await baseline.latest(repo, ids["ua"], now)
    assert done["status"] == "submitted"
    assert done["results"][0]["code"] == "CHEST" and done["results"][0]["questions"] == QUESTIONS
    async with _repo(engine, ids["tb"]) as repo:
        with pytest.raises(baseline.BaselineMissing):
            await baseline.latest(repo, ids["ub"], now)
        with pytest.raises(baseline.NotEnoughQuestions):
            await baseline.start(repo, ids["ub"], now, seed=1)


async def _service_proof(runtime_dsn: str, ids: dict[str, Any]) -> None:
    from apps.api.app.study import reports, service
    from sqlalchemy.ext.asyncio import create_async_engine

    now = datetime.now(UTC)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        async with _repo(engine, ids["ta"]) as repo:
            progress = await service.progress(repo, ids["ua"], now)
        chest = next(t for t in progress["topics"] if t["code"] == "CHEST")
        assert progress["weight_policy"] == "past_paper_approved"
        assert chest["questions"] == QUESTIONS and chest["attempts"] == 1
        assert chest["accuracy"] == 1.0
        await _baseline_proof(engine, ids, now)
        async with _repo(engine, ids["ta"]) as repo:
            await reports.store_weekly_report(repo, ids["ua"], now)
        async with _repo(engine, ids["ta"]) as repo:
            assert (await reports.latest_report(repo, ids["ua"]))["weight_policy"]
            plan = await service.plan_for_tomorrow(repo, ids["ua"], now)
        assert plan["weight_policy"] == "past_paper_approved"
        async with _repo(engine, ids["tb"]) as repo:
            assert await repo.latest_report(ids["ua"]) is None
            assert await repo.question_counts(ids["ua"]) == []
            assert await repo.approved_weights(ids["ua"]) == []
    finally:
        await engine.dispose()


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _rls_proof(runtime, ids)
        await _resolver_proof(runtime, ids)
        await _service_proof(runtime_dsn, ids)
    finally:
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_study_depth_tables_resolvers_and_services_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
