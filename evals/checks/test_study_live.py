"""Opt-in live proof for the study tables and service (migration 0006).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* every new tenant table hides tenant A's rows from tenant B, rejects writes
  with a foreign tenant_id, and shows nothing without tenant context;
* card_reviews is append-only for the runtime role;
* the real study service creates a cited card from an owned chunk, reviews it
  with FSRS, and plans the day, while tenant B cannot cite tenant A's chunk.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from packages.library import storage  # noqa: E402

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
CITATION = '{"source_id": "%s", "page_from": 1, "page_to": 1}'


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("study live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the study proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "sa", "sb", "ca", "card")}
    async with admin.transaction():
        await admin.execute(
            "INSERT INTO tenants (id, kind, name) VALUES ($1,'personal','Study A'),"
            "($2,'personal','Study B')", ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"study-{ids[user]}", f"{ids[user]}@example.invalid")
        for source, tenant, user in (("sa", "ta", "ua"), ("sb", "tb", "ub")):
            await admin.execute(
                "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, "
                "storage_key, title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic')",
                ids[source], ids[tenant], ids[user], uuid4().hex + uuid4().hex,
                storage.original_key(ids[tenant], ids[source], "pdf"))
        await admin.execute(
            "INSERT INTO chunks (id, tenant_id, source_id, chunk_no, page_from, page_to, heading, "
            "text, block_refs) VALUES ($1,$2,$3,0,1,1,'PAP','Crazy paving on HRCT.',"
            "'[{\"page\":1,\"block\":0}]')", ids["ca"], ids["ta"], ids["sa"])
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("card_reviews", "cards", "study_plans", "study_profiles", "chunks",
                      "audit_log", "sources"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


def _inserts(ids: dict[str, UUID]) -> dict[str, tuple[str, tuple[Any, ...]]]:
    ta, ua, sa = ids["ta"], ids["ua"], ids["sa"]
    later = date.today() + timedelta(days=100)
    return {
        "study_profiles": ("INSERT INTO study_profiles (tenant_id, user_id, exam_date) "
                           "VALUES ($1,$2,$3)", (ta, ua, later)),
        "study_plans": ("INSERT INTO study_plans (tenant_id, user_id, plan_date, phase, "
                        "days_remaining, minutes, plan_version, blocks) "
                        "VALUES ($1,$2,$3,'coverage',200,60,1,'[]')", (ta, ua, date.today())),
        "cards": ("INSERT INTO cards (id, tenant_id, user_id, source_id, curriculum_code, topic, "
                  "front, back, citation) VALUES ($4,$1,$2,$3,'CHEST','PAP','Q?','A.',"
                  f"'{CITATION % sa}')", (ta, ua, sa, ids["card"])),
        "card_reviews": ("INSERT INTO card_reviews (tenant_id, user_id, card_id, rating, "
                         "elapsed_days, scheduled_days, state_before, stability_after, "
                         "difficulty_after) VALUES ($1,$2,$3,3,0,3,'new',3.1,5.3)",
                         (ta, ua, ids["card"])),
    }


async def _rls_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    for table, (sql, args) in _inserts(ids).items():
        await _as_tenant(runtime, ids["ta"], sql, *args)
        assert await _as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table
        assert await _as_tenant(runtime, None, f"SELECT 1 FROM {table}") == [], table
        assert len(await _as_tenant(runtime, ids["ta"], f"SELECT 1 FROM {table}")) == 1, table
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_tenant(runtime, ids["tb"], sql, *args)
        if table == "card_reviews":
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                await _as_tenant(runtime, ids["ta"], "UPDATE card_reviews SET rating = 1")
        else:
            moved = await _as_tenant(
                runtime, ids["tb"], f"UPDATE {table} SET tenant_id = $1 RETURNING 1", ids["tb"])
            assert moved == [], table
        deleted = await _as_tenant(runtime, ids["tb"], f"DELETE FROM {table} RETURNING 1")
        assert deleted == [], table
    for table in ("card_reviews", "cards", "study_plans", "study_profiles"):
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


async def _service_proof(runtime_dsn: str, ids: dict[str, UUID]) -> None:
    from apps.api.app.study import service
    from sqlalchemy.ext.asyncio import create_async_engine

    now = datetime.now(UTC)
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    profile = {"exam_date": now.date() + timedelta(days=120), "exam_targets": ["fcps2_toacs"],
               "daily_minutes": 60, "weekday_minutes": None, "weekend_minutes": None,
               "timezone": "UTC", "reminder": {"enabled": False, "time": None}}
    fields = {"chunk_id": ids["ca"], "curriculum_code": "CHEST", "topic": "PAP",
              "front": "HRCT sign of PAP?", "back": "Crazy paving."}
    try:
        async with _repo(engine, ids["ta"]) as repo:
            await service.save_profile(repo, ids["ua"], profile, now)
        async with _repo(engine, ids["ta"]) as repo:
            card = await service.create_card(repo, ids["ua"], fields, now)
        assert card["citation"]["source_id"] == str(ids["sa"])
        async with _repo(engine, ids["ta"]) as repo:
            reviewed = await service.review_card(repo, ids["ua"], card["id"], 3, now)
        assert reviewed["scheduled_days"] == 3
        async with _repo(engine, ids["ta"]) as repo:
            plan = await service.today_plan(repo, ids["ua"], now)
        assert sum(b["minutes"] for b in plan["blocks"]) == 60
        async with _repo(engine, ids["ta"]) as repo:
            report = await service.progress(repo, ids["ua"], now)
        assert report["reviews_total"] == 1 and report["cards"] == 1
        async with _repo(engine, ids["tb"]) as repo:
            with pytest.raises(service.NotFound):
                await service.create_card(repo, ids["ub"], fields, now)
            assert await service.due_cards(repo, ids["ub"], now, 50) == []
            assert await repo.get_card(ids["ub"], card["id"]) is None
    finally:
        await engine.dispose()


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _rls_proof(runtime, ids)
        await _service_proof(runtime_dsn, ids)
    finally:
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_study_tables_and_service_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
