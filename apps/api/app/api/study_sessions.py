"""Today session runner and progress insights (ADR 0024).

Shares the study router's principal, repository and clock dependencies, so a
test override of those applies here too. Every route is scoped to the calling
user inside their tenant's RLS context; another user's session answers 404.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from apps.api.app.api import exams as exams_api
from apps.api.app.api.study import NowDep, PrincipalDep, get_repo
from apps.api.app.schemas.study_sessions import InsightsOut, StepAnswerIn, StudySessionOut
from apps.api.app.study import insights as insights_uc
from apps.api.app.study import service, sessions
from apps.api.app.study.ports import SessionRepo
from fastapi import APIRouter, Depends, HTTPException, Path, Query

router = APIRouter(prefix="/v1/study", tags=["study"])


def session_repo(repo: Annotated[service.StudyRepo, Depends(get_repo)]) -> SessionRepo:
    return cast(SessionRepo, repo)


RepoDep = Annotated[SessionRepo, Depends(session_repo)]
StepNo = Annotated[int, Path(ge=1, le=20)]


def _fail(exc: service.StudyError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/sessions/today", response_model=StudySessionOut,
            responses={409: {"description": "Set your exam date first"}})
async def today_session(principal: PrincipalDep, repo: RepoDep, now: NowDep) -> StudySessionOut:
    """Build (once per local day) or resume today's session."""
    try:
        view = await sessions.today_session(repo, principal.user_id, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return StudySessionOut.model_validate(view)


@router.post("/sessions/{session_id}/steps/{step_no}/start", response_model=StudySessionOut)
async def start_step(session_id: UUID, step_no: StepNo, principal: PrincipalDep,
                     repo: RepoDep, now: NowDep) -> StudySessionOut:
    try:
        view = await sessions.start_step(repo, principal.user_id, session_id, step_no, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return StudySessionOut.model_validate(view)


@router.post("/sessions/{session_id}/steps/{step_no}/answer", response_model=StudySessionOut)
async def answer_step(session_id: UUID, step_no: StepNo, body: StepAnswerIn,
                      principal: PrincipalDep, repo: RepoDep, now: NowDep) -> StudySessionOut:
    """Answer one SBA item (with optional confidence 1-3) or the viva prompt."""
    try:
        view, grading = await sessions.answer(
            repo, principal.user_id, session_id, step_no, body.model_dump(mode="json"), now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    if grading is not None:
        exams_api.enqueue_grading(principal.tenant_id, grading.exam_id, grading.question_ids)
    return StudySessionOut.model_validate(view)


@router.post("/sessions/{session_id}/steps/{step_no}/complete", response_model=StudySessionOut)
async def complete_step(session_id: UUID, step_no: StepNo, principal: PrincipalDep,
                        repo: RepoDep, now: NowDep,
                        skip: Annotated[bool, Query()] = False) -> StudySessionOut:
    try:
        view = await sessions.complete_step(
            repo, principal.user_id, session_id, step_no, now, skip)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return StudySessionOut.model_validate(view)


@router.post("/sessions/{session_id}/complete", response_model=StudySessionOut)
async def complete_session(session_id: UUID, principal: PrincipalDep, repo: RepoDep,
                           now: NowDep) -> StudySessionOut:
    """Finish the day: unfinished steps are skipped and the summary is frozen."""
    try:
        view = await sessions.complete_session(repo, principal.user_id, session_id, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return StudySessionOut.model_validate(view)


@router.get("/insights", response_model=InsightsOut,
            responses={409: {"description": "Set your exam date first"}})
async def insights(principal: PrincipalDep, repo: RepoDep, now: NowDep) -> InsightsOut:
    """Coverage heatmap, days-remaining projection and calibration bias."""
    try:
        view = await insights_uc.insights(repo, principal.user_id, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return InsightsOut.model_validate(view)
