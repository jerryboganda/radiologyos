"""Grounded tutor API (ADR 0013): ask (JSON or SSE), list threads, read a thread.

``POST /v1/tutor/ask`` retrieves the top excerpts and described figures from
the caller's own library, asks the tutor agents through the model transport,
verifies every citation, runs the semantic grounding judge, and stores the
exchange. The model calls can take minutes: they run in a threadpool with no
database transaction open.

``POST /v1/tutor/ask/stream`` does the same work but answers with Server-Sent
Events: ``status`` (``retrieving``, ``answering``, ``web_research``,
``judging``), then ``answer`` (the JSON route's body) and ``done``. Failures
arrive as one ``error`` event carrying the JSON route's status code (404, 429,
502, 503). Only progress streams; the model output is one validated JSON.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.api.library import query_vector
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import set_database_tenant
from apps.api.app.library import search
from apps.api.app.observability import logger
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from apps.api.app.tutor import repo
from apps.api.app.tutor.stream import (
    HEARTBEAT,
    SSE_HEADERS,
    Finished,
    error_event,
    sse,
    status_event,
    with_progress,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from packages.models.claude_code import ClaudeCodeTransport, ModelCallError, UsageLimitError
from packages.models.gateway import Transport
from packages.tutor.grounding import Excerpt, FigureExcerpt, excerpts_from_hits, figures_from_hits
from packages.tutor.judge import StatusCallback
from packages.tutor.models import GroundedAnswer, Grounding, JudgeStats, Segment
from packages.tutor.orchestrator import Turn, answer_question
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/tutor", tags=["tutor"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
RETRIEVE = 8
FIGURE_CANDIDATES = 12
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")
UNAVAILABLE = ("The tutor is unavailable: the Claude Code CLI is not installed on the "
               "API server, so no model can be called.")


def model_transport() -> Transport | None:
    """The production model transport, or None when the CLI is absent; tests override."""
    transport = ClaudeCodeTransport(get_settings().claude_code_bin)
    return transport if transport.available() else None


OptionalTransportDep = Annotated[Transport | None, Depends(model_transport)]


def get_transport(transport: OptionalTransportDep) -> Transport:
    if transport is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    return transport


TransportDep = Annotated[Transport, Depends(get_transport)]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=2000)
    thread_id: UUID | None = None
    allow_web: bool = True


class AskResponse(BaseModel):
    thread_id: UUID
    message_id: UUID
    grounding: Grounding
    segments: list[Segment]
    notice: str | None
    dropped_segments: int
    agent_version: str
    excerpts_considered: int
    figures_considered: int
    judge: JudgeStats | None


class ThreadSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ThreadMessage(BaseModel):
    id: UUID
    role: str
    content: str
    grounding: Grounding | None
    segments: list[Segment]
    agent_version: str
    created_at: datetime
    judge: JudgeStats | None = None


class ThreadDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ThreadMessage]


@dataclass(frozen=True, slots=True)
class Prepared:
    history: list[Turn]
    excerpts: list[Excerpt]
    figures: list[FigureExcerpt]


def lexical_query(question: str) -> str:
    """OR the question's terms so a natural-language question still matches.

    ``websearch_to_tsquery`` ANDs plain words; a full question rarely matches
    one chunk on every word. Stop words are dropped by the text search config.
    """
    terms = list(dict.fromkeys(t.lower() for t in TOKEN.findall(question)))[:40]
    return " or ".join(terms) if terms else question


async def _prepare(session: AsyncSession, principal: Principal, body: AskRequest) -> Prepared:
    """Check the thread, load history, and retrieve excerpts and figures (404 if no thread)."""
    history: list[Turn] = []
    if body.thread_id is not None:
        if await repo.get_thread(session, principal.user_id, body.thread_id) is None:
            raise HTTPException(status_code=404, detail="thread not found")
        history = await repo.recent_history(session, body.thread_id)
    vector = await query_vector(principal.tenant_id, body.question)
    query = lexical_query(body.question)
    hits = await search.hybrid_search(session, principal.user_id, query, vector, RETRIEVE)
    figures = await search.search_figures(session, principal.user_id, query, FIGURE_CANDIDATES,
                                          query_vector=vector)
    await session.rollback()  # hold no transaction or connection during the model calls
    return Prepared(history, excerpts_from_hits(hits), figures_from_hits(figures))


def _answer(
    transport: Transport, body: AskRequest, prepared: Prepared,
    on_status: StatusCallback | None = None,
) -> GroundedAnswer:
    return answer_question(
        transport, body.question, prepared.excerpts, prepared.history, body.allow_web,
        figures=prepared.figures, judge=get_settings().tutor_grounding_judge,
        on_status=on_status,
    )


def _model_error(exc: ModelCallError) -> HTTPException:
    logger.warning("tutor_model_failed", extra={"error_type": type(exc).__name__})
    if isinstance(exc, UsageLimitError):
        return HTTPException(status_code=429, detail="The model usage window is exhausted; "
                             "try the tutor again later.")
    return HTTPException(status_code=502, detail="The tutor model call failed; try again.")


async def _persist(
    session: AsyncSession, principal: Principal, body: AskRequest, answer: GroundedAnswer,
    prepared: Prepared,
) -> AskResponse:
    await set_database_tenant(session, principal.tenant_id)
    thread_id = body.thread_id or await repo.create_thread(
        session, principal.tenant_id, principal.user_id, repo.thread_title(body.question)
    )
    message_id = await repo.add_exchange(
        session, principal.tenant_id, thread_id, body.question, answer
    )
    await session.commit()
    judge = answer.judge or JudgeStats(status="not_run")
    logger.info("tutor_answered", extra={
        "thread_id": str(thread_id), "message_id": str(message_id),
        "grounding": answer.grounding, "segments": len(answer.segments),
        "dropped_segments": answer.dropped_segments, "excerpts": len(prepared.excerpts),
        "figures": len(prepared.figures), "judge_status": judge.status,
        "judge_partial": judge.partial, "judge_unsupported": judge.unsupported,
    })
    return AskResponse(
        thread_id=thread_id, message_id=message_id, grounding=answer.grounding,
        segments=answer.segments, notice=answer.notice,
        dropped_segments=answer.dropped_segments, agent_version=answer.agent_version,
        excerpts_considered=len(prepared.excerpts), figures_considered=len(prepared.figures),
        judge=answer.judge,
    )


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest, principal: PrincipalDep, session: SessionDep, transport: TransportDep
) -> AskResponse:
    prepared = await _prepare(session, principal, body)
    try:
        answer = await run_in_threadpool(_answer, transport, body, prepared)
    except ModelCallError as exc:
        raise _model_error(exc) from exc
    return await _persist(session, principal, body, answer, prepared)


async def _ask_events(
    body: AskRequest, principal: Principal, session: AsyncSession, transport: Transport | None
) -> AsyncIterator[str]:
    if transport is None:
        yield error_event(503, UNAVAILABLE)
        return
    yield status_event("retrieving")
    try:
        prepared = await _prepare(session, principal, body)
        answer: GroundedAnswer | None = None
        async for item in with_progress(partial(_answer, transport, body, prepared)):
            if isinstance(item, Finished):
                answer = item.value
            else:
                yield HEARTBEAT if item is None else status_event(item)
        if answer is None:  # defensive: with_progress always finishes or raises
            raise ModelCallError("tutor produced no answer")
        response = await _persist(session, principal, body, answer, prepared)
    except HTTPException as exc:
        yield error_event(exc.status_code, str(exc.detail))
        return
    except ModelCallError as exc:
        failure = _model_error(exc)
        yield error_event(failure.status_code, str(failure.detail))
        return
    except Exception as exc:  # the stream must always end with an event
        logger.error("tutor_stream_failed", extra={"error_type": type(exc).__name__})
        yield error_event(500, "The tutor failed unexpectedly; try again.")
        return
    yield sse("answer", response.model_dump(mode="json"))
    yield sse("done", {"thread_id": str(response.thread_id),
                       "message_id": str(response.message_id)})


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    responses={200: {
        "description": "Server-Sent Events: status*, then answer + done, or one error.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }},
)
async def ask_stream(
    body: AskRequest, principal: PrincipalDep, session: SessionDep,
    transport: OptionalTransportDep,
) -> StreamingResponse:
    return StreamingResponse(_ask_events(body, principal, session, transport),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/threads", response_model=list[ThreadSummary])
async def list_threads(principal: PrincipalDep, session: SessionDep) -> list[ThreadSummary]:
    return [ThreadSummary(**row) for row in await repo.list_threads(session, principal.user_id)]


def _message(row: dict[str, Any]) -> ThreadMessage:
    segments, judge = repo.stored_answer(row["citations"])
    return ThreadMessage(
        id=row["id"], role=row["role"], content=row["content"], grounding=row["grounding"],
        segments=[Segment.model_validate(s) for s in segments],
        agent_version=row["agent_version"], created_at=row["created_at"],
        judge=JudgeStats.model_validate(judge) if judge else None,
    )


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: UUID, principal: PrincipalDep, session: SessionDep
) -> ThreadDetail:
    thread = await repo.get_thread(session, principal.user_id, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    messages = [_message(m) for m in await repo.thread_messages(session, thread_id)]
    return ThreadDetail(**thread, messages=messages)
