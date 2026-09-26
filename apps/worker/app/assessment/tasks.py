"""Celery entry points for asynchronous exam grading and item statistics (ADR 0015)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING
from uuid import UUID

from apps.worker.app.celery_app import celery_app

if TYPE_CHECKING:
    from packages.models.gateway import Transport
    from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.assessment")
DEFER_SECONDS = 30 * 60
RETRY_SECONDS = 60


def _build() -> tuple[AsyncEngine, Transport | None]:
    from apps.worker.app.ingest.db import make_engine
    from packages.models.claude_code import ClaudeCodeTransport

    transport = ClaudeCodeTransport(os.environ.get("CLAUDE_CODE_BIN", "claude"))
    has_token = bool(
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    )
    return make_engine(), transport if transport.available() and has_token else None


@celery_app.task(  # type: ignore[untyped-decorator]
    name="radbrain.grade_exam_item", bind=True, acks_late=True, max_retries=5
)
def grade_exam_item(self: object, tenant_id: str, exam_id: str, question_id: str) -> str:
    """Grade (or resume grading) one free-text exam item.

    Idempotent on (tenant, exam, question, grading version): a graded or failed
    job is a no-op, and a usage-limit pause or model error re-queues the task.
    """
    from apps.worker.app.assessment.grading import grade_item

    async def run() -> str:
        engine, transport = _build()
        try:
            return await grade_item(engine, transport, UUID(tenant_id), UUID(exam_id),
                                    UUID(question_id))
        finally:
            await engine.dispose()

    outcome = asyncio.run(run())
    args = [tenant_id, exam_id, question_id]
    if outcome == "deferred":
        delay = int(os.environ.get("INGEST_DEFER_SECONDS", DEFER_SECONDS))
        grade_exam_item.apply_async(args=args, countdown=delay)
    elif outcome == "retry":
        grade_exam_item.apply_async(args=args, countdown=RETRY_SECONDS)
    return outcome


@celery_app.task(name="radbrain.recompute_item_stats")  # type: ignore[untyped-decorator]
def recompute_item_stats(tenant_id: str, user_id: str) -> int:
    """Recompute one owner's item statistics inside that owner's tenant context."""
    from apps.worker.app.assessment.grading import recompute_stats
    from apps.worker.app.ingest.db import make_engine

    async def run() -> int:
        engine = make_engine()
        try:
            return await recompute_stats(engine, UUID(tenant_id), UUID(user_id))
        finally:
            await engine.dispose()

    retired = asyncio.run(run())
    log.info("item stats recomputed retired=%s", retired)
    return retired
