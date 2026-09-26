"""Celery entry point for knowledge extraction (ADR 0016)."""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

from apps.worker.app.celery_app import celery_app

log = logging.getLogger("radbrain.knowledge")
DEFER_SECONDS = 30 * 60


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.knowledge_extract", bind=True, acks_late=True, max_retries=5
)
def knowledge_extract(
    self: object, tenant_id: str, source_id: str, mode: str = "notes",
    exam_target: str | None = None, year: int | None = None,
) -> str:
    """Extract (or resume extracting) knowledge for one source.

    Idempotent on (tenant, source, unit content hash, agent version, pipeline
    version); a usage-limit pause re-queues the same arguments.
    """
    from apps.worker.app.knowledge.pipeline import run_knowledge
    from apps.worker.app.knowledge.runtime import build_knowledge_deps

    async def run() -> str:
        deps = build_knowledge_deps()
        try:
            return await run_knowledge(deps, UUID(tenant_id), UUID(source_id), mode,
                                       exam_target, year)
        finally:
            await deps.engine.dispose()

    outcome = asyncio.run(run())
    log.info("knowledge source=%s mode=%s outcome=%s", source_id, mode, outcome)
    if outcome == "deferred":
        delay = int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS))
        knowledge_extract.apply_async(
            args=[tenant_id, source_id, mode, exam_target, year], countdown=delay
        )
    return outcome
