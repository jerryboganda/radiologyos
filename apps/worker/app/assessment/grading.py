"""Grade one pending free-text exam item (idempotent per exam, question, version).

1. In a tenant transaction: lock the job; stop unless it is claimable; read
   the frozen question and the saved answer; mark the job running.
2. Outside any transaction: grade with ``seq_grade`` (may take minutes).
3. In a tenant transaction: store the outcome; a final outcome fills the item
   into the exam result and appends the attempt; when no job of the exam is
   still open, item statistics for the owner are recomputed.

Only ids, statuses, and error codes are logged, never answers or prompts.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from apps.api.app.assessment import exams, grading_store, item_stats, store
from apps.api.app.core.time import now_utc
from apps.worker.app.ingest.db import tenant_tx
from packages.assessment.grading_jobs import Outcome, claimable, run_grading
from packages.models.gateway import Transport
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.assessment")


async def grade_item(
    engine: AsyncEngine, transport: Transport | None, tenant_id: UUID, exam_id: UUID,
    question_id: UUID,
) -> str:
    """Return the run's outcome: graded, failed, deferred, retry, done, busy, or missing."""
    async with tenant_tx(engine, tenant_id) as session:
        job = await grading_store.load_job(session, exam_id, question_id, lock=True)
        if job is None:
            return "missing"
        if not claimable(job["status"], job["updated_at"], now_utc()):
            return "busy" if job["status"] == "running" else "done"
        exam = await exams.load_exam(session, job["user_id"], exam_id)
        question = await store.get_question(session, job["user_id"], question_id)
        await grading_store.start_run(session, job["id"])
    if exam is None or question is None:
        outcome = Outcome("failed", error="item_missing")
    else:
        answer = str((exam.get("text_answers") or {}).get(str(question_id), ""))
        outcome = await asyncio.to_thread(
            run_grading, transport, question, answer, job["errors"], job["runs"])
    async with tenant_tx(engine, tenant_id) as session:
        await grading_store.finish(session, job, outcome)
        if outcome.status != "pending" and await grading_store.open_count(session, exam_id) == 0:
            await item_stats.recompute(session, tenant_id, job["user_id"])
    log.info("grading exam=%s question=%s outcome=%s code=%s", exam_id, question_id,
             outcome.kind, outcome.error)
    return outcome.kind


async def recompute_stats(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> int:
    async with tenant_tx(engine, tenant_id) as session:
        outcome = await item_stats.recompute(session, tenant_id, user_id)
    return len(outcome["retired"])
