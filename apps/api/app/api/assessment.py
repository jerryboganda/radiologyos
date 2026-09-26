"""Assessment API: question generation (duplicate-checked), bank, and attempts.

Exam routes live in ``apps.api.app.api.exams`` and the review queue and item
statistics in ``apps.api.app.api.question_review``; both share this module's
principal, session, and transport dependencies so test overrides apply to all.

Model calls (generation, checking, free-text grading) run in a worker thread
with the database transaction committed first, so no connection sits idle in a
transaction while the model works; the tenant setting is re-applied before the
writes. Answer keys never leave the API for a question that is part of one of
the caller's open exams.
"""

from __future__ import annotations

from typing import Annotated, Any, Protocol
from uuid import UUID

from apps.api.app.api.library import query_vector
from apps.api.app.assessment import dedupe, exams, generation, retrieval, store
from apps.api.app.assessment.contracts import (
    AttemptRequest,
    AttemptResponse,
    GenerateRequest,
    GenerateResponse,
    QuestionPublic,
    RejectedItem,
    public_question,
)
from apps.api.app.db.session import set_database_tenant
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from packages.assessment import agents
from packages.assessment.grading import (
    ExamError,
    InvalidAnswer,
    apply_seq_grade,
    grade_sba,
)
from packages.models.claude_code import (
    ClaudeCodeTransport,
    ModelCall,
    ModelCallError,
    ModelResult,
    UsageLimitError,
)
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1", tags=["assessment"])

SEQ_GRADER = "seq_grade/v1"


class ModelTransport(Protocol):
    def available(self) -> bool: ...

    def run(self, call: ModelCall) -> ModelResult: ...


def get_transport() -> ModelTransport:
    return ClaudeCodeTransport()


PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
TransportDep = Annotated[ModelTransport, Depends(get_transport)]


def _require_model(transport: ModelTransport) -> None:
    if not transport.available():
        raise HTTPException(status_code=503, detail="model runtime is not available")


def _model_error(exc: ModelCallError) -> HTTPException:
    if isinstance(exc, UsageLimitError):
        return HTTPException(status_code=503, detail="model usage limit reached; retry later")
    return HTTPException(status_code=502, detail="model call failed")


def _exam_error(exc: ExamError) -> HTTPException:
    code = 422 if isinstance(exc, InvalidAnswer) else 409
    return HTTPException(status_code=code, detail=exc.code)


@router.post("/questions/generate", response_model=GenerateResponse,
             status_code=status.HTTP_201_CREATED)
async def generate_questions(
    body: GenerateRequest, principal: PrincipalDep, session: SessionDep, transport: TransportDep
) -> GenerateResponse:
    _require_model(transport)
    vector = await run_in_threadpool(query_vector, body.topic) if body.topic else None
    excerpts = await retrieval.gather_excerpts(
        session, principal.user_id, body.topic, body.source_ids, vector,
        with_figure=body.type in ("image_case", "viva"))
    if not any(e.ref.startswith("E") for e in excerpts):
        raise HTTPException(status_code=422, detail="no source material matched")
    if body.type == "image_case" and not any(e.figure_id for e in excerpts):
        raise HTTPException(status_code=422, detail="no described figure matched")
    await session.commit()
    try:
        outcome = await run_in_threadpool(
            generation.generate_items, transport, excerpts, body.type, body.exam_target,
            body.count, body.topic)
    except ModelCallError as exc:
        raise _model_error(exc) from exc
    stems = [values["stem"] for values in outcome.items]
    vectors, embed_model = await run_in_threadpool(dedupe.embed_stems, stems)
    await set_database_tenant(session, principal.tenant_id)
    stored = await dedupe.insert_unique(
        session, principal.tenant_id, principal.user_id,
        list(zip(outcome.indexes, outcome.items, strict=True)), vectors, embed_model)
    rows = await store.get_questions(session, principal.user_id, stored.created)
    await session.commit()
    duplicates = [
        RejectedItem(index=index, reasons=["duplicate_of_existing"], duplicate_of=hit.question_id,
                     similarity=hit.similarity)
        for index, hit in stored.duplicates
    ]
    return GenerateResponse(
        created=[public_question(rows[str(qid)]) for qid in stored.created],
        rejected=[RejectedItem(**r) for r in outcome.rejected] + duplicates,
        excerpt_count=len(excerpts),
        duplicate_method="embedding" if stored.method == "embedding" else "trigram",
    )


@router.get("/questions", response_model=list[QuestionPublic])
async def list_questions(
    principal: PrincipalDep,
    session: SessionDep,
    type: Annotated[str | None, Query(pattern="^(sba|seq|image_case|viva|rapid_recall)$")] = None,
    exam_target: Annotated[str | None, Query(pattern="^(fcps2_theory|fcps2_toacs|imm|frcr)$")]
    = None,
    topic: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    status_: Annotated[str | None, Query(alias="status", pattern="^(draft|active|retired)$")]
    = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[QuestionPublic]:
    rows = await store.list_questions(session, principal.user_id, {
        "type": type, "exam_target": exam_target, "topic": topic, "status": status_,
        "limit": limit, "offset": offset,
    })
    return [public_question(row) for row in rows]


def _sba_response(attempt_id: UUID | None, question: dict[str, Any],
                  graded: dict[str, Any]) -> AttemptResponse:
    return AttemptResponse(
        attempt_id=attempt_id, question_id=question["id"], type="sba",
        score=graded["score"], max_score=graded["max_score"], correct=graded["correct"],
        key=graded["key"], explanation=graded["explanation"],
        option_explanations=graded["option_explanations"], citations=graded["citations"],
    )


async def _attempt_sba(session: AsyncSession, principal: Principal, question: dict[str, Any],
                       selected: int | None) -> AttemptResponse:
    if selected is None:
        raise HTTPException(status_code=422, detail="selected_option is required")
    graded = grade_sba(question, selected)
    attempt_id = await store.insert_attempt(session, principal.tenant_id, principal.user_id, {
        "question_id": question["id"], "response": {"selected_option": selected},
        "score": graded["score"], "max_score": graded["max_score"],
        "feedback": {"correct": graded["correct"]}, "graded_by": exams.SBA_GRADER,
    })
    await session.commit()
    return _sba_response(attempt_id, question, graded)


async def _attempt_free_text(
    session: AsyncSession, principal: Principal, question: dict[str, Any],
    answer_text: str | None, transport: ModelTransport,
) -> AttemptResponse:
    if not answer_text:
        raise HTTPException(status_code=422, detail="answer_text is required")
    _require_model(transport)
    await session.commit()
    try:
        grade = await run_in_threadpool(agents.grade_free_text, transport, question, answer_text)
    except ModelCallError as exc:
        raise _model_error(exc) from exc
    answer = question["answer"]
    graded = apply_seq_grade(answer["marking_scheme"], grade)
    await set_database_tenant(session, principal.tenant_id)
    attempt_id = await store.insert_attempt(session, principal.tenant_id, principal.user_id, {
        "question_id": question["id"], "response": {"answer_text": answer_text},
        "score": graded["score"], "max_score": graded["max_score"],
        "feedback": {"points": graded["points"], "feedback": graded["feedback"]},
        "graded_by": SEQ_GRADER,
    })
    await session.commit()
    return AttemptResponse(
        attempt_id=attempt_id, question_id=question["id"], type=question["type"],
        score=graded["score"], max_score=graded["max_score"],
        explanation=question["explanation"], points=graded["points"],
        feedback=graded["feedback"], model_answer=answer.get("model_answer", ""),
        key_findings=answer.get("key_findings", []), citations=question["citations"],
    )


@router.post("/questions/{question_id}/attempt", response_model=AttemptResponse)
async def attempt_question(
    question_id: UUID, body: AttemptRequest, principal: PrincipalDep, session: SessionDep,
    transport: TransportDep,
) -> AttemptResponse:
    question = await store.get_question(session, principal.user_id, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="question not found")
    if await store.in_open_exam(session, principal.user_id, question_id):
        raise HTTPException(status_code=409, detail="question is in an open exam")
    if question["type"] == "sba":
        try:
            return await _attempt_sba(session, principal, question, body.selected_option)
        except InvalidAnswer as exc:
            raise _exam_error(exc) from exc
    if question["type"] == "rapid_recall":
        raise HTTPException(status_code=422, detail="rapid recall is graded by review")
    return await _attempt_free_text(session, principal, question, body.answer_text, transport)
