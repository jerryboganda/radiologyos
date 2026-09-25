from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.app.api.preview import preview_principal_context
from apps.api.app.preview.assessment import (
    autosave_exam,
    create_exam,
    grade,
    list_questions,
    question_view,
    start_exam,
    submit_exam,
)
from apps.api.app.preview.contracts import (
    PreviewAttemptRequest,
    PreviewAttemptResponse,
    PreviewAutosaveRequest,
    PreviewExamResponse,
    PreviewExamResultResponse,
    PreviewMasteryResponse,
    PreviewPracticeResponse,
    PreviewQuestionResponse,
)
from apps.api.app.preview.learning import mastery
from apps.api.app.preview.service import get_preview_state, require_preview
from apps.api.app.preview.state import PreviewExam, PreviewQuestion
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(
    prefix="/v1/preview",
    tags=["preview: non-release"],
    dependencies=[Depends(require_preview)],
)


def _question_response(question: PreviewQuestion) -> PreviewQuestionResponse:
    return PreviewQuestionResponse.model_validate(question_view(question))


def _exam_response(exam: PreviewExam) -> PreviewExamResponse:
    questions = list_questions(get_preview_state(), exam.tenant_id, exam.owner_id)
    by_id = {question.id: question for question in questions}
    return PreviewExamResponse(
        exam_id=str(exam.id),
        status=exam.status,
        revision=exam.revision,
        questions=tuple(
            _question_response(by_id[question_id]) for question_id in exam.question_ids
        ),
        saved_answers={str(question_id): option for question_id, option in exam.answers.items()},
        deadline_at=exam.deadline_at,
    )


@router.get("/questions", response_model=tuple[PreviewQuestionResponse, ...])
def questions(
    principal: Annotated[Principal, Depends(preview_principal_context)],
    curriculum_code: str | None = None,
    limit: int = 5,
) -> tuple[PreviewQuestionResponse, ...]:
    if not 1 <= limit <= 20:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
    selected = [
        question
        for question in list_questions(get_preview_state(), principal.tenant_id, principal.user_id)
        if curriculum_code is None or question.curriculum_code == curriculum_code
    ][:limit]
    return tuple(_question_response(question) for question in selected)


@router.post("/practice", response_model=PreviewPracticeResponse)
def practice(
    principal: Annotated[Principal, Depends(preview_principal_context)],
    curriculum_code: str | None = None,
    limit: int = 5,
) -> PreviewPracticeResponse:
    if not 1 <= limit <= 20:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
    selected = [
        question
        for question in list_questions(get_preview_state(), principal.tenant_id, principal.user_id)
        if curriculum_code is None or question.curriculum_code == curriculum_code
    ][:limit]
    return PreviewPracticeResponse(
        questions=tuple(_question_response(question) for question in selected)
    )


@router.post("/attempts", response_model=PreviewAttemptResponse)
def attempt(
    payload: PreviewAttemptRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewAttemptResponse:
    try:
        result = grade(
            get_preview_state(),
            principal.tenant_id,
            principal.user_id,
            UUID(payload.question_id),
            payload.selected_option,
        )
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreviewAttemptResponse(
        attempt_id=str(result["attempt_id"]),
        grade=result["grade"],
        mastery=PreviewMasteryResponse.model_validate(
            mastery(get_preview_state(), principal.tenant_id, principal.user_id)
        ),
    )


@router.post("/exams", response_model=PreviewExamResponse)
def new_exam(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewExamResponse:
    return _exam_response(create_exam(get_preview_state(), principal.tenant_id, principal.user_id))


@router.get("/exams/{exam_id}", response_model=PreviewExamResponse)
def get_exam(
    exam_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewExamResponse:
    exam = get_preview_state().exam(principal.tenant_id, exam_id)
    if exam is None or exam.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="exam not found")
    return _exam_response(exam)


@router.post("/exams/{exam_id}/start", response_model=PreviewExamResponse)
def start(
    exam_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewExamResponse:
    try:
        exam = start_exam(get_preview_state(), principal.tenant_id, principal.user_id, exam_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _exam_response(exam)


@router.post("/exams/{exam_id}/autosave", response_model=PreviewExamResponse)
def autosave(
    exam_id: UUID,
    payload: PreviewAutosaveRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewExamResponse:
    answers = {UUID(key): value for key, value in payload.answers.items()}
    try:
        exam = autosave_exam(
            get_preview_state(),
            principal.tenant_id,
            principal.user_id,
            exam_id,
            payload.revision,
            answers,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _exam_response(exam)


@router.post("/exams/{exam_id}/submit", response_model=PreviewExamResultResponse)
def submit(
    exam_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewExamResultResponse:
    try:
        result = submit_exam(get_preview_state(), principal.tenant_id, principal.user_id, exam_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PreviewExamResultResponse.model_validate(result)
