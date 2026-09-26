"""SQL for asynchronous free-text exam grading jobs (shared by the API and worker).

A job row exists once per (tenant, exam, question, grading version); creating
it again is a no-op. The worker claims a job, grades outside any transaction,
then in one transaction stores the job outcome, fills the graded item into the
exam's stored result, and appends the attempt (unique per exam and question).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.assessment import store
from packages.assessment.exam_result import failed_item, fill_item, graded_free_text
from packages.assessment.grading_jobs import GRADER, GRADING_VERSION, Outcome
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_job(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, exam_id: UUID, question_id: UUID
) -> None:
    await session.execute(
        text(
            "INSERT INTO grading_jobs (tenant_id, user_id, exam_id, question_id, grader, "
            "pipeline_version) VALUES (:t, :u, :e, :q, :g, :v) "
            "ON CONFLICT (tenant_id, exam_id, question_id, pipeline_version) DO NOTHING"
        ),
        {"t": tenant_id, "u": user_id, "e": exam_id, "q": question_id, "g": GRADER,
         "v": GRADING_VERSION},
    )


async def load_job(
    session: AsyncSession, exam_id: UUID, question_id: UUID, lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, user_id, exam_id, question_id, status, runs, errors, "
                "error_code, updated_at FROM grading_jobs WHERE exam_id = :e "
                f"AND question_id = :q AND pipeline_version = :v{suffix}"  # nosec B608 - constant suffix; values are bound
            ),
            {"e": exam_id, "q": question_id, "v": GRADING_VERSION},
        )
    ).mappings().first()
    return dict(row) if row else None


async def start_run(session: AsyncSession, job_id: UUID) -> None:
    await session.execute(
        text("UPDATE grading_jobs SET status = 'running', runs = runs + 1 WHERE id = :j"),
        {"j": job_id},
    )


async def stale_pending(
    session: AsyncSession, user_id: UUID, exam_id: UUID, before: datetime
) -> list[UUID]:
    """Pending/running jobs untouched since ``before``; touched so one reader re-queues."""
    rows = await session.execute(
        text(
            "UPDATE grading_jobs SET updated_at = now() WHERE user_id = :u AND exam_id = :e "
            "AND status IN ('pending', 'running') AND updated_at < :before "
            "RETURNING question_id"
        ),
        {"u": user_id, "e": exam_id, "before": before},
    )
    return [row[0] for row in rows]


async def record_attempt(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, exam_id: UUID,
    item: dict[str, Any], grader: str,
) -> None:
    await store.insert_attempt(session, tenant_id, user_id, {
        "question_id": UUID(item["question_id"]), "exam_id": exam_id,
        "response": {"answer_text": item["answer_text"]},
        "score": item["score"], "max_score": item["max_score"],
        "feedback": {"points": item["points"], "feedback": item["feedback"]},
        "graded_by": grader,
    })


async def _fill_exam(
    session: AsyncSession, exam_id: UUID, question_id: str, outcome: Outcome
) -> dict[str, Any] | None:
    """Update the stored exam result in place; returns the filled item, if any."""
    row = (
        await session.execute(
            text("SELECT result FROM exams WHERE id = :e AND result IS NOT NULL FOR UPDATE"),
            {"e": exam_id},
        )
    ).first()
    if row is None:
        return None
    result = row[0]
    current = next((i for i in result["items"] if i["question_id"] == question_id), None)
    if current is None or current.get("status") != "pending":
        return None
    if outcome.graded is not None:
        item = graded_free_text(current, outcome.graded)
    else:
        item = failed_item(current, outcome.error or "grading_failed")
    await session.execute(
        text("UPDATE exams SET result = CAST(:r AS jsonb) WHERE id = :e"),
        {"r": store.dumps(fill_item(result, question_id, item)), "e": exam_id},
    )
    return item


async def finish(session: AsyncSession, job: dict[str, Any], outcome: Outcome) -> None:
    """Store the outcome; a final outcome also fills the exam result and the attempt."""
    await session.execute(
        text(
            "UPDATE grading_jobs SET status = :s, error_code = :c, "
            "errors = errors + :err, result = CAST(:r AS jsonb) WHERE id = :j"
        ),
        {"s": outcome.status, "c": outcome.error, "j": job["id"],
         "err": 1 if outcome.error == "model_error" else 0,
         "r": store.dumps(outcome.graded) if outcome.graded is not None else None},
    )
    if outcome.status == "pending":
        return
    item = await _fill_exam(session, job["exam_id"], str(job["question_id"]), outcome)
    if item is not None and item["status"] == "graded":
        await record_attempt(session, job["tenant_id"], job["user_id"], job["exam_id"], item,
                             GRADER)


async def open_count(session: AsyncSession, exam_id: UUID) -> int:
    row = await session.execute(
        text("SELECT count(*) FROM grading_jobs WHERE exam_id = :e "
             "AND status IN ('pending', 'running')"),
        {"e": exam_id},
    )
    return int(row.scalar_one())
