"""Timed exam routes: create, autosave, submit, read, and list.

Exams may mix SBA with SEQ, image-case, and viva items. On submission SBA items
are graded at once; each answered free-text item gets a grading job that the
worker runs through ``seq_grade`` and fills into the stored result, so the
result reports ``pending`` items until they are graded. Enqueueing happens only
after the transaction commits; reading an exam re-queues jobs that have sat
untouched for too long (a lost broker message or a dead worker). Item
statistics are recomputed by the worker once an exam is fully graded.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from apps.api.app.api.assessment import PrincipalDep, SessionDep
from apps.api.app.assessment import exams, grading_store, store
from apps.api.app.assessment.contracts import (
    AutosaveRequest,
    AutosaveResponse,
    ExamCreate,
    ExamSummary,
    ExamView,
    public_question,
)
from apps.api.app.core.time import now_utc
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, HTTPException, status
from packages.assessment.exam_result import pending_ids
from packages.assessment.grading import ExamError, InvalidAnswer, exam_status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/v1", tags=["assessment"])
log = logging.getLogger("radbrain.assessment")
REQUEUE_AFTER = timedelta(minutes=10)


def enqueue_grading(tenant_id: UUID, exam_id: UUID, question_ids: list[str]) -> None:
    """Best effort: a job left pending is re-queued by a later read of the exam."""
    if not question_ids:
        return
    try:
        from apps.worker.app.celery_app import celery_app

        for question_id in question_ids:
            celery_app.send_task("radbrain.grade_exam_item",
                                 args=[str(tenant_id), str(exam_id), str(question_id)])
    except Exception:
        log.warning("grading enqueue failed exam=%s", exam_id)


def enqueue_stats(tenant_id: UUID, user_id: UUID) -> None:
    """Best effort: statistics can always be recomputed on demand."""
    try:
        from apps.worker.app.celery_app import celery_app

        celery_app.send_task("radbrain.recompute_item_stats", args=[str(tenant_id), str(user_id)])
    except Exception:
        log.warning("item stats enqueue failed")


def _exam_error(exc: ExamError) -> HTTPException:
    code = 422 if isinstance(exc, InvalidAnswer) else 409
    return HTTPException(status_code=code, detail=exc.code)


async def _exam_view(session: AsyncSession, principal: Principal,
                     row: dict[str, Any]) -> ExamView:
    ids = list(row["question_ids"])
    found = await store.get_questions(session, principal.user_id, ids)
    now = now_utc()
    return ExamView(
        id=row["id"], mode=row["mode"], status=exam_status(exams.state_of(row), now),
        config=row["config"], started_at=row["started_at"], deadline_at=row["deadline_at"],
        submitted_at=row["submitted_at"], server_time=now, revision=row["revision"],
        answers=dict(row["answers"] or {}), text_answers=dict(row.get("text_answers") or {}),
        questions=[public_question(found[str(q)]) for q in ids if str(q) in found],
        result=row["result"],
    )


async def _to_enqueue(session: AsyncSession, principal: Principal,
                      row: dict[str, Any]) -> list[str]:
    """Pending items to hand to the worker: all when just submitted, else stale ones."""
    pending = pending_ids(row.get("result"))
    if not pending or row.get("just_submitted"):
        return pending
    stale = await grading_store.stale_pending(
        session, principal.user_id, row["id"], now_utc() - REQUEUE_AFTER)
    return [str(q) for q in stale]


@router.post("/exams", response_model=ExamView, status_code=status.HTTP_201_CREATED)
async def create_exam(body: ExamCreate, principal: PrincipalDep, session: SessionDep) -> ExamView:
    try:
        exam_id = await exams.create_exam(
            session, principal.tenant_id, principal.user_id, body.model_dump())
    except exams.NotEnoughQuestions as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = await exams.load_exam(session, principal.user_id, exam_id)
    if row is None:
        raise HTTPException(status_code=500, detail="exam was not stored")
    view = await _exam_view(session, principal, row)
    await session.commit()
    return view


@router.put("/exams/{exam_id}/answers", response_model=AutosaveResponse)
async def autosave_exam(
    exam_id: UUID, body: AutosaveRequest, principal: PrincipalDep, session: SessionDep
) -> AutosaveResponse:
    try:
        saved = await exams.save_answers(
            session, principal.user_id, exam_id, body.revision, body.answers, body.text_answers)
    except ExamError as exc:
        raise _exam_error(exc) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail="exam not found")
    await session.commit()
    return AutosaveResponse(exam_id=exam_id, revision=saved["revision"],
                            deadline_at=saved["deadline_at"], answers=saved["answers"],
                            text_answers=saved["text_answers"])


async def _finish_view(session: AsyncSession, principal: Principal,
                       row: dict[str, Any]) -> ExamView:
    view = await _exam_view(session, principal, row)
    queue = await _to_enqueue(session, principal, row)
    await session.commit()
    enqueue_grading(principal.tenant_id, row["id"], queue)
    if row.get("just_submitted") and not queue:
        enqueue_stats(principal.tenant_id, principal.user_id)
    return view


@router.post("/exams/{exam_id}/submit", response_model=ExamView)
async def submit_exam(exam_id: UUID, principal: PrincipalDep, session: SessionDep) -> ExamView:
    row = await exams.submit(session, principal.tenant_id, principal.user_id, exam_id)
    if row is None:
        raise HTTPException(status_code=404, detail="exam not found")
    return await _finish_view(session, principal, row)


@router.get("/exams", response_model=list[ExamSummary])
async def list_exams(
    principal: PrincipalDep, session: SessionDep, limit: int = 50
) -> list[ExamSummary]:
    now = now_utc()
    rows = await exams.list_exams(session, principal.user_id, max(1, min(limit, 200)))
    return [
        ExamSummary(
            id=row["id"], mode=row["mode"], status=exam_status(exams.state_of(row), now),
            started_at=row["started_at"], deadline_at=row["deadline_at"],
            submitted_at=row["submitted_at"], question_count=len(row["question_ids"] or []),
            answered=len(row["answers"] or {}) + len(row.get("text_answers") or {}),
            score_percent=(row["result"] or {}).get("percent"),
            pending_grading=len(pending_ids(row["result"])),
        )
        for row in rows
    ]


@router.get("/exams/{exam_id}", response_model=ExamView)
async def get_exam(exam_id: UUID, principal: PrincipalDep, session: SessionDep) -> ExamView:
    row = await exams.read_exam(session, principal.tenant_id, principal.user_id, exam_id)
    if row is None:
        raise HTTPException(status_code=404, detail="exam not found")
    return await _finish_view(session, principal, row)
