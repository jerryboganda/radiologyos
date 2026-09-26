"""Study beat tasks: weekly reports (Monday morning, local) and nightly replans.

Each task asks a narrow SECURITY DEFINER resolver *which* users are due; the
resolvers return (tenant_id, user_id) only. Everything else runs through the
study service under that tenant's transaction-local RLS context as the runtime
role. Both tasks are idempotent: a report is unique per (user, week) and a
plan per (user, date) at the current ``PLANNER_VERSION``, and the resolvers
skip users already done. Logs carry counts and error classes only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.worker.app.celery_app import celery_app
from apps.worker.app.ingest.db import make_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

log = logging.getLogger("radbrain.study_jobs")
UserJob = Callable[[Any, UUID, datetime], Awaitable[Any]]


@asynccontextmanager
async def _tenant_repo(engine: AsyncEngine, tenant_id: UUID) -> AsyncIterator[Any]:
    from apps.api.app.study.repo import SqlStudyRepo

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"),
                              {"t": str(tenant_id)})
        yield SqlStudyRepo(session, tenant_id)


async def _due(engine: AsyncEngine, sql: str, params: dict[str, Any]) -> list[tuple[UUID, UUID]]:
    async with AsyncSession(engine) as session:
        rows = (await session.execute(text(sql), params)).all()
    return [(UUID(str(tenant)), UUID(str(user))) for tenant, user in rows]


async def run_for_due(
    engine: AsyncEngine, sql: str, params: dict[str, Any], job: UserJob, now: datetime
) -> int:
    """Run ``job`` once per due user; one user's failure never blocks the rest."""
    done = 0
    for tenant_id, user_id in await _due(engine, sql, params):
        try:
            async with _tenant_repo(engine, tenant_id) as repo:
                await job(repo, user_id, now)
            done += 1
        except Exception as exc:  # noqa: BLE001 - isolate users; log the class only
            log.warning("study job failed kind=%s", type(exc).__name__)
    return done


def _run(sql: str, params: dict[str, Any], job: UserJob, now: datetime) -> int:
    async def run() -> int:
        engine = make_engine()
        try:
            return await run_for_due(engine, sql, params, job, now)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@celery_app.task(name="radbrain.weekly_reports")  # type: ignore[untyped-decorator]
def weekly_reports() -> int:
    from apps.api.app.study.reports import store_weekly_report

    now = datetime.now(UTC)
    done = _run("SELECT tenant_id, user_id FROM app.weekly_reports_due(:now)",
                {"now": now}, store_weekly_report, now)
    if done:
        log.info("weekly reports stored=%s", done)
    return done


@celery_app.task(name="radbrain.nightly_replan")  # type: ignore[untyped-decorator]
def nightly_replan() -> int:
    from apps.api.app.study.service import plan_for_tomorrow
    from packages.study.planner import PLANNER_VERSION

    now = datetime.now(UTC)
    done = _run("SELECT tenant_id, user_id FROM app.study_replans_due(:now, :v)",
                {"now": now, "v": PLANNER_VERSION}, plan_for_tomorrow, now)
    if done:
        log.info("nightly replans=%s", done)
    return done
