"""Celery entry points for knowledge extraction (ADR 0016) and depth (ADR 0030)."""

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
    if outcome == "continue":
        knowledge_extract.apply_async(
            args=[tenant_id, source_id, mode, exam_target, year], countdown=1
        )
    if outcome == "deferred":
        delay = int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS))
        knowledge_extract.apply_async(
            args=[tenant_id, source_id, mode, exam_target, year], countdown=delay
        )
    if outcome == "succeeded" and mode == "notes" and depth_enabled():
        knowledge_depth.apply_async(args=[tenant_id, source_id, True], countdown=1)
    return outcome


def depth_enabled() -> bool:
    """``KNOWLEDGE_DEPTH_AUTO=0`` stops the automatic depth pass (ADR 0030)."""
    return os.environ.get("KNOWLEDGE_DEPTH_AUTO", "1") == "1"


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.knowledge_depth", bind=True, acks_late=True, max_retries=5
)
def knowledge_depth(self: object, tenant_id: str, source_id: str, fresh: bool = False) -> str:
    """Conflict, Resolver and Synthesis agents for one source (ADR 0030).

    Idempotent on (tenant, source, unit, agent version, pipeline version) via
    ``knowledge_runs``; status is the job step ``knowledge_depth``.
    """
    from apps.worker.app.knowledge.depth import run_depth
    from apps.worker.app.knowledge.runtime import build_knowledge_deps

    async def run() -> str:
        deps = build_knowledge_deps()
        try:
            return await run_depth(deps, UUID(tenant_id), UUID(source_id), fresh)
        finally:
            await deps.engine.dispose()

    outcome = asyncio.run(run())
    log.info("knowledge_depth source=%s outcome=%s", source_id, outcome)
    if outcome == "continue":
        knowledge_depth.apply_async(args=[tenant_id, source_id, False], countdown=1)
    if outcome == "deferred":
        delay = int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS))
        knowledge_depth.apply_async(args=[tenant_id, source_id, False], countdown=delay)
    return outcome


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.concept_note", bind=True, acks_late=True, max_retries=3
)
def concept_note(self: object, tenant_id: str, user_id: str, concept_id: str) -> str:
    """(Re)write one owner's note for one concept; a no-op when its claims are unchanged."""
    from apps.worker.app.knowledge.concept_notes import synthesize_concept
    from apps.worker.app.knowledge.runtime import Deferred, build_knowledge_deps

    async def run() -> str:
        deps = build_knowledge_deps()
        try:
            return await synthesize_concept(deps, UUID(tenant_id), UUID(user_id),
                                            UUID(concept_id))
        except Deferred:
            return "deferred"
        finally:
            await deps.engine.dispose()

    outcome = asyncio.run(run())
    log.info("concept_note concept=%s outcome=%s", concept_id, outcome)
    if outcome == "deferred":
        delay = int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS))
        concept_note.apply_async(args=[tenant_id, user_id, concept_id], countdown=delay)
    return outcome
