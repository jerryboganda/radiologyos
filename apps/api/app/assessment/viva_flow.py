"""Apply examiner work to a session and finish it (shared by the API and the worker).

``apply_outcome`` runs inside the tenant transaction that closes one worker
step; ``finish`` computes the debrief in code (no model call), marks any
unanswered or ungraded turn skipped, records a bank attempt for a staged case
built on a question, and hands weak turns to the weakness-loop seam.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.assessment import store, viva_store
from apps.api.app.assessment.weakness import report_weak_areas, weak_areas
from packages.assessment.viva import PIPELINE_VERSION, StopReason, debrief
from packages.assessment.viva_steps import StepOutcome
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("radbrain.assessment")
STAGED_GRADER = "seq_grade/v1:staged"


def enqueue_step(tenant_id: UUID, session_id: UUID, turn_no: int) -> None:
    """Best effort: a lost message is re-queued by a later read of the session."""
    try:
        from apps.worker.app.celery_app import celery_app

        celery_app.send_task("radbrain.viva_step", args=[
            str(tenant_id), str(session_id), int(turn_no), PIPELINE_VERSION])
    except Exception:
        log.warning("viva enqueue failed session=%s turn=%s", session_id, turn_no)


async def request_work(db: AsyncSession, session_id: UUID, turn_no: int) -> None:
    await viva_store.update_session(db, session_id, {
        "work": "pending", "work_turn": turn_no, "runs": 0, "errors": 0, "error_code": None})


async def apply_outcome(
    db: AsyncSession, row: Mapping[str, Any], outcome: StepOutcome, now: datetime
) -> None:
    sid: UUID = row["id"]
    if outcome.kind in ("deferred", "retry"):
        errors = int(row["errors"]) + (1 if outcome.kind == "retry" else 0)
        await viva_store.update_session(db, sid, {
            "work": "pending", "errors": errors, "error_code": outcome.error})
        return
    if outcome.kind == "failed":
        await _fail(db, row, outcome.error or "examiner_failed", now)
        return
    updates: dict[str, Any] = {**outcome.session, "work": "none", "error_code": None}
    if outcome.question is not None:
        updates["question_id"] = await store.insert_question(
            db, row["tenant_id"], row["user_id"], outcome.question)
    if outcome.graded is not None:
        await viva_store.grade_turn(db, sid, outcome.graded["turn_no"],
                                    outcome.graded["evaluation"])
    if outcome.new_turn is not None:
        await viva_store.insert_turn(db, row["tenant_id"], row["user_id"], sid,
                                     outcome.new_turn)
    await viva_store.update_session(db, sid, updates)
    if outcome.finish is not None:
        await finish(db, {**row, **updates}, outcome.finish, now)


async def _fail(db: AsyncSession, row: Mapping[str, Any], code: str, now: datetime) -> None:
    turns = await viva_store.load_turns(db, row["id"])
    if any(t["status"] == "graded" for t in turns):
        await viva_store.update_session(db, row["id"], {"error_code": code})
        await finish(db, row, "examiner_error", now)
        return
    await viva_store.skip_open_turns(db, row["id"])
    await viva_store.update_session(db, row["id"], {
        "status": "failed", "work": "none", "error_code": code})


async def finish(
    db: AsyncSession, row: Mapping[str, Any], reason: StopReason, now: datetime
) -> dict[str, Any]:
    """Close the session with a code-computed debrief; idempotent on a finished session."""
    if row["status"] == "finished" and row.get("debrief"):
        return dict(row["debrief"])
    await viva_store.skip_open_turns(db, row["id"])
    turns = await viva_store.load_turns(db, row["id"])
    result = debrief(turns, reason, row["kind"])
    areas = weak_areas(row, turns)
    result["weak_areas"] = len(areas)
    await viva_store.update_session(db, row["id"], {
        "status": "finished", "work": "none", "finished_at": now, "stop_reason": reason,
        "debrief": result})
    await _record_staged_attempt(db, row, result)
    await report_weak_areas(db, areas)
    return result


async def _record_staged_attempt(
    db: AsyncSession, row: Mapping[str, Any], result: Mapping[str, Any]
) -> None:
    """A staged case on a bank question counts as one attempt of that question."""
    question_id = row.get("question_id")
    stages = result.get("stages") or []
    if row["kind"] != "image_case" or question_id is None or not stages:
        return
    rubric = (row.get("case_data") or {}).get("stages") or []
    max_score = round(sum(float(p["marks"]) for r in rubric for p in r["marking_scheme"]), 2)
    if max_score <= 0:
        return
    score = round(sum(float(s["score"]) for s in stages), 2)
    await store.insert_attempt(db, row["tenant_id"], row["user_id"], {
        "question_id": question_id, "response": {"viva_session_id": str(row["id"])},
        "score": min(score, max_score), "max_score": max_score,
        "feedback": {"stage_scores": list(stages)}, "graded_by": STAGED_GRADER,
    })

