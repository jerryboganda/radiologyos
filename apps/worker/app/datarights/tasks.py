"""Celery entry points for account export and deletion, export expiry, and retention.

Both jobs are idempotent and resumable (see export.py and delete.py): a failure
is recorded by error class only, the job returns to ``queued``, and Celery
retries it with backoff; the last failure marks it ``failed``. The beat task
``radbrain.expire_data_exports`` deletes export objects and rows once they
expire, finding them through the ids-only ``app.expired_data_exports``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.worker.app.celery_app import celery_app
from apps.worker.app.datarights import jobs
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("radbrain.datarights")
Runner = Callable[[jobs.DataDeps, UUID, UUID], Awaitable[str]]


def build_data_deps() -> jobs.DataDeps:
    from apps.worker.app.ingest.db import make_engine
    from apps.worker.app.ingest.runtime import object_store

    return jobs.DataDeps(engine=make_engine(), store=object_store())


def _run(task: Any, runner: Runner, tenant_id: str, job_id: str) -> str:
    async def run() -> str:
        deps = build_data_deps()
        try:
            try:
                return await runner(deps, UUID(tenant_id), UUID(job_id))
            except Exception as exc:
                final = task.request.retries >= task.max_retries
                await jobs.fail(deps.engine, UUID(tenant_id), UUID(job_id),
                                type(exc).__name__, final)
                raise
        finally:
            await deps.engine.dispose()

    try:
        outcome = asyncio.run(run())
    except Exception as exc:
        log.warning("data job=%s failed error=%s", job_id, type(exc).__name__)
        if task.request.retries >= task.max_retries:
            return "failed"
        raise task.retry(countdown=60 * (task.request.retries + 1)) from exc
    log.info("data job=%s outcome=%s", job_id, outcome)
    return outcome


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.data_export", bind=True, acks_late=True, max_retries=3
)
def data_export(self: Any, tenant_id: str, job_id: str) -> str:
    from apps.worker.app.datarights.export import run_export

    return _run(self, run_export, tenant_id, job_id)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.data_delete", bind=True, acks_late=True, max_retries=5
)
def data_delete(self: Any, tenant_id: str, job_id: str) -> str:
    from apps.worker.app.datarights.delete import run_delete

    return _run(self, run_delete, tenant_id, job_id)


@celery_app.task(name="radbrain.expire_data_exports")  # type: ignore[untyped-decorator]
def expire_data_exports() -> int:
    async def run() -> int:
        deps = build_data_deps()
        try:
            return await expire(deps, datetime.now(UTC))
        finally:
            await deps.engine.dispose()

    return asyncio.run(run())


@celery_app.task(name="radbrain.retention_purge")  # type: ignore[untyped-decorator]
def retention_purge() -> dict[str, int]:
    """Daily retention pass; a no-op unless RETENTION_PURGE_MODE opts in (ADR 0020)."""
    from apps.worker.app.datarights import retention

    mode = retention.configured_mode()
    if mode == "off":
        return {"due": 0, "purged": 0}

    async def run() -> dict[str, int]:
        deps = build_data_deps()
        try:
            return await retention.sweep(deps, datetime.now(UTC), mode,
                                         retention.configured_months())
        finally:
            await deps.engine.dispose()

    outcome = asyncio.run(run())
    log.info("retention mode=%s due=%s purged=%s", mode, outcome["due"], outcome["purged"])
    return outcome


async def expire(deps: jobs.DataDeps, now: datetime) -> int:
    """Delete every expired export: object first, then its row."""
    from apps.worker.app.ingest.db import tenant_tx
    from packages.library import storage

    async with AsyncSession(deps.engine) as session:
        due = (
            await session.execute(
                text("SELECT tenant_id, job_id FROM app.expired_data_exports(:now)"),
                {"now": now},
            )
        ).all()
    for tenant_id, job_id in due:
        tenant, job = UUID(str(tenant_id)), UUID(str(job_id))
        deps.store.delete_prefix(storage.export_key(tenant, job))
        async with tenant_tx(deps.engine, tenant) as tx:
            await tx.execute(
                text("DELETE FROM data_jobs WHERE id = :id AND kind = 'export' "
                     "AND expires_at <= :now"),
                {"id": job, "now": now},
            )
    if due:
        log.info("expired exports=%s", len(due))
    return len(due)
