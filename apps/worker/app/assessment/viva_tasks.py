"""Celery entry point for viva and staged image-case examiner work (ADR 0026)."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

from apps.worker.app.assessment.tasks import DEFER_SECONDS, RETRY_SECONDS, _build
from apps.worker.app.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.viva_step", bind=True, acks_late=True, max_retries=5
)
def viva_step(self: object, tenant_id: str, session_id: str, turn_no: int, version: int) -> str:
    """Open, grade, or prepare one turn of a session.

    Idempotent on (session, turn, pipeline version): work already applied, or
    superseded by an early end, is a no-op; a usage-limit pause or a model
    error re-queues the task.
    """
    from apps.worker.app.assessment.viva import run_viva_step

    async def run() -> str:
        engine, transport = _build()
        try:
            return await run_viva_step(engine, transport, UUID(tenant_id), UUID(session_id),
                                       int(turn_no), int(version))
        finally:
            await engine.dispose()

    outcome = asyncio.run(run())
    args = [tenant_id, session_id, turn_no, version]
    if outcome == "deferred":
        delay = int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS))
        viva_step.apply_async(args=args, countdown=delay)
    elif outcome == "retry":
        viva_step.apply_async(args=args, countdown=RETRY_SECONDS)
    return outcome
