"""Timed exam lifecycle: create, autosave (compare-and-set), submit, finalise.

The server owns the clock: the deadline is fixed at creation, autosaves after
it are refused, and an expired exam is graded from its last saved answers the
next time it is read or submitted. Submission is idempotent: the stored result
is returned unchanged on every later call. Answer keys appear only in the
stored result, which exists only once the exam is submitted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from apps.api.app.assessment import store
from apps.api.app.core.time import now_utc
from packages.assessment.grading import ExamState, autosave, exam_status, grade_exam
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SBA_GRADER = "rule:sba_exact"
_EXAM_COLUMNS = (
    "id, mode, config, question_ids, started_at, deadline_at, submitted_at, revision, "
    "answers, result, created_at"
)


class NotEnoughQuestions(LookupError):
    pass


def state_of(row: dict[str, Any]) -> ExamState:
    return ExamState(
        mode=row["mode"], question_ids=list(row["question_ids"]),
        deadline_at=row["deadline_at"], submitted_at=row["submitted_at"],
        revision=row["revision"], answers=dict(row["answers"] or {}),
    )


async def create_exam(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, config: dict[str, Any]
) -> UUID:
    ids = await store.pick_exam_questions(
        session, user_id, config.get("exam_target"), config.get("topic"), config["count"])
    if not ids:
        raise NotEnoughQuestions("no active SBA questions match these filters")
    started = now_utc()
    minutes = config.get("time_limit_minutes")
    deadline = started + timedelta(minutes=minutes) if minutes else None
    row = await session.execute(
        text(
            "INSERT INTO exams (tenant_id, user_id, mode, config, question_ids, started_at, "
            "deadline_at) VALUES (:t, :u, :mode, CAST(:config AS jsonb), "
            "CAST(:ids AS uuid[]), :started, :deadline) RETURNING id"
        ),
        {"t": tenant_id, "u": user_id, "mode": config["mode"],
         "config": store.dumps({**config, "available": len(ids)}), "ids": ids,
         "started": started, "deadline": deadline},
    )
    exam_id: UUID = row.scalar_one()
    return exam_id


async def load_exam(
    session: AsyncSession, user_id: UUID, exam_id: UUID, lock: bool = False
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        await session.execute(
            text(f"SELECT {_EXAM_COLUMNS} FROM exams WHERE id = :e AND user_id = :u{suffix}"),
            {"e": exam_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def save_answers(
    session: AsyncSession,
    user_id: UUID,
    exam_id: UUID,
    revision: int,
    answers: dict[str, int | None],
) -> dict[str, Any] | None:
    """Apply a compare-and-set autosave; raises ExamError subclasses on refusal."""
    row = await load_exam(session, user_id, exam_id, lock=True)
    if row is None:
        return None
    merged = autosave(state_of(row), revision, answers, now_utc())
    updated = (
        await session.execute(
            text(
                "UPDATE exams SET answers = CAST(:a AS jsonb), revision = revision + 1 "
                "WHERE id = :e AND user_id = :u AND revision = :r AND submitted_at IS NULL "
                "RETURNING revision, answers, deadline_at"
            ),
            {"a": store.dumps(merged), "e": exam_id, "u": user_id, "r": revision},
        )
    ).mappings().first()
    return dict(updated) if updated else None


async def submit(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, exam_id: UUID
) -> dict[str, Any] | None:
    """Grade and close the exam once; later calls return the stored result."""
    row = await load_exam(session, user_id, exam_id, lock=True)
    if row is None:
        return None
    if row["submitted_at"] is not None:
        return row
    state = state_of(row)
    questions = await store.get_questions(session, user_id, state.question_ids)
    submitted_at = now_utc()
    result = grade_exam(state, questions)
    result["timed_out"] = _late(state.deadline_at, submitted_at)
    await session.execute(
        text(
            "UPDATE exams SET submitted_at = :s, result = CAST(:r AS jsonb) "
            "WHERE id = :e AND user_id = :u AND submitted_at IS NULL"
        ),
        {"s": submitted_at, "r": store.dumps(result), "e": exam_id, "u": user_id},
    )
    for item in result["items"]:
        await store.insert_attempt(session, tenant_id, user_id, {
            "question_id": UUID(item["question_id"]), "exam_id": exam_id,
            "response": {"selected_option": item["selected_option"]},
            "score": item["score"], "max_score": item["max_score"],
            "feedback": {"correct": item["correct"]}, "graded_by": SBA_GRADER,
        })
    return {**row, "submitted_at": submitted_at, "result": result}


async def read_exam(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, exam_id: UUID
) -> dict[str, Any] | None:
    """Load an exam, finalising it first if its deadline has passed."""
    row = await load_exam(session, user_id, exam_id)
    if row is not None and exam_status(state_of(row), now_utc()) == "expired":
        return await submit(session, tenant_id, user_id, exam_id)
    return row


def _late(deadline: datetime | None, at: datetime) -> bool:
    return deadline is not None and at >= deadline
