"""Grounded tutor API (ADR 0013): ask, list threads, read a thread.

``POST /v1/tutor/ask`` retrieves the top excerpts from the caller's own library,
asks the tutor agents through the model transport, verifies every citation,
and stores the exchange. The model call can take minutes: it runs in a
threadpool with no database transaction open, and the endpoint answers
synchronously (streaming over SSE is a planned follow-up).
"""

from __future__ import annotations

import re
from datetime import datetime
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
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from packages.models.claude_code import ClaudeCodeTransport, ModelCallError, UsageLimitError
from packages.models.gateway import Transport
from packages.tutor.grounding import excerpts_from_hits
from packages.tutor.models import GroundedAnswer, Grounding, Segment
from packages.tutor.orchestrator import Turn, answer_question
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/tutor", tags=["tutor"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
RETRIEVE = 8
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")


def get_transport() -> Transport:
    """The production model transport; tests override this dependency."""
    transport = ClaudeCodeTransport(get_settings().claude_code_bin)
    if not transport.available():
        raise HTTPException(
            status_code=503,
            detail="The tutor is unavailable: the Claude Code CLI is not installed on the "
                   "API server, so no model can be called.",
        )
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


class ThreadDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ThreadMessage]


def lexical_query(question: str) -> str:
    """OR the question's terms so a natural-language question still matches.

    ``websearch_to_tsquery`` ANDs plain words; a full question rarely matches
    one chunk on every word. Stop words are dropped by the text search config.
    """
    terms = list(dict.fromkeys(t.lower() for t in TOKEN.findall(question)))[:40]
    return " or ".join(terms) if terms else question


async def _retrieve(
    session: AsyncSession, principal: Principal, question: str
) -> list[dict[str, Any]]:
    vector = await run_in_threadpool(query_vector, question)
    return await search.hybrid_search(
        session, principal.user_id, lexical_query(question), vector, RETRIEVE
    )


def _model_error(exc: ModelCallError) -> HTTPException:
    if isinstance(exc, UsageLimitError):
        return HTTPException(status_code=429, detail="The model usage window is exhausted; "
                             "try the tutor again later.")
    return HTTPException(status_code=502, detail="The tutor model call failed; try again.")


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest, principal: PrincipalDep, session: SessionDep, transport: TransportDep
) -> AskResponse:
    history: list[Turn] = []
    if body.thread_id is not None:
        if await repo.get_thread(session, principal.user_id, body.thread_id) is None:
            raise HTTPException(status_code=404, detail="thread not found")
        history = await repo.recent_history(session, body.thread_id)
    excerpts = excerpts_from_hits(await _retrieve(session, principal, body.question))
    await session.rollback()  # hold no transaction or connection during the model call
    try:
        answer: GroundedAnswer = await run_in_threadpool(
            answer_question, transport, body.question, excerpts, history, body.allow_web
        )
    except ModelCallError as exc:
        logger.warning("tutor_model_failed", extra={"error_type": type(exc).__name__})
        raise _model_error(exc) from exc
    await set_database_tenant(session, principal.tenant_id)
    thread_id = body.thread_id or await repo.create_thread(
        session, principal.tenant_id, principal.user_id, repo.thread_title(body.question)
    )
    message_id = await repo.add_exchange(
        session, principal.tenant_id, thread_id, body.question, answer
    )
    await session.commit()
    logger.info("tutor_answered", extra={
        "thread_id": str(thread_id), "message_id": str(message_id),
        "grounding": answer.grounding, "segments": len(answer.segments),
        "dropped_segments": answer.dropped_segments, "excerpts": len(excerpts),
    })
    return AskResponse(
        thread_id=thread_id, message_id=message_id, grounding=answer.grounding,
        segments=answer.segments, notice=answer.notice,
        dropped_segments=answer.dropped_segments, agent_version=answer.agent_version,
        excerpts_considered=len(excerpts),
    )


@router.get("/threads", response_model=list[ThreadSummary])
async def list_threads(principal: PrincipalDep, session: SessionDep) -> list[ThreadSummary]:
    return [ThreadSummary(**row) for row in await repo.list_threads(session, principal.user_id)]


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: UUID, principal: PrincipalDep, session: SessionDep
) -> ThreadDetail:
    thread = await repo.get_thread(session, principal.user_id, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    messages = [
        ThreadMessage(
            id=m["id"], role=m["role"], content=m["content"], grounding=m["grounding"],
            segments=[Segment.model_validate(s) for s in m["citations"] or []],
            agent_version=m["agent_version"], created_at=m["created_at"],
        )
        for m in await repo.thread_messages(session, thread_id)
    ]
    return ThreadDetail(**thread, messages=messages)
