from __future__ import annotations

import asyncio
import logging
import os
from typing import TypedDict
from uuid import UUID

from apps.worker.app.celery_app import celery_app
from apps.worker.app.ops.pausing import defer_delay

log = logging.getLogger("radbrain.worker")
DEFER_SECONDS = 30 * 60


class HealthResult(TypedDict):
    status: str
    service: str


@celery_app.task(name="radbrain.health")  # type: ignore[untyped-decorator]
def health() -> HealthResult:
    """Return process liveness without contacting a model or database."""

    return {"status": "ok", "service": "worker"}


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.ingest_source", bind=True, acks_late=True, max_retries=5
)
def ingest_source(self: object, tenant_id: str, job_id: str) -> str:
    """Run (or resume) the ingestion pipeline for one job.

    Idempotent on (tenant, source, step, pipeline version): succeeded steps and
    parsed pages are skipped on re-run. A usage-limit pause re-queues the task.
    """
    from apps.worker.app.ingest.runtime import build_deps
    from apps.worker.app.ingest.steps import run_ingest

    async def run() -> str:
        deps = build_deps()
        try:
            return await run_ingest(deps, UUID(tenant_id), UUID(job_id))
        finally:
            await deps.engine.dispose()

    outcome = asyncio.run(run())
    log.info("ingest job=%s outcome=%s", job_id, outcome)
    if outcome == "continue":
        ingest_source.apply_async(args=[tenant_id, job_id], countdown=1)
    if outcome == "deferred":
        delay = defer_delay(int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS)))
        ingest_source.apply_async(args=[tenant_id, job_id], countdown=delay)
    return outcome


@celery_app.task(name="radbrain.quota_alert")  # type: ignore[untyped-decorator]
def quota_alert(tenant_id: str, provider: str, until: float) -> str:
    """Tell the owner the pipeline is paused on a provider quota (ADR 0037)."""
    from apps.worker.app.ingest.db import make_engine
    from apps.worker.app.ops.escalations import quota_paused

    async def run() -> None:
        engine = make_engine()
        try:
            await quota_paused(engine, UUID(tenant_id), provider, until)
        finally:
            await engine.dispose()

    asyncio.run(run())
    return "alerted"


@celery_app.task(name="radbrain.approve_escalations")  # type: ignore[untyped-decorator]
def approve_escalations(tenant_id: str, user_id: str) -> str:
    """The owner approved Opus for the saved items (Settings, ADR 0037)."""
    from apps.worker.app.ingest.db import make_engine
    from apps.worker.app.ops.pipeline_control import approve

    async def run() -> dict[str, int]:
        engine = make_engine()
        try:
            return await approve(engine, UUID(tenant_id), UUID(user_id))
        finally:
            await engine.dispose()

    counts = asyncio.run(run())
    log.info("approve_escalations %s", counts)
    return "approved"
