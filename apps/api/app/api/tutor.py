"""Grounded tutor API (ADR 0013, ADR 0025): ask (JSON or SSE), threads, images.

``POST /v1/tutor/ask`` retrieves the top excerpts and described figures from
the caller's own library (the Reader page first when ``focus`` is given, and
steered by the AI reading of an attached image), asks the tutor agents through
the model gateway, verifies every citation, runs the semantic grounding judge,
and stores the exchange with the thread's rolling memory. Model calls run in a
threadpool with no database transaction open (``apps.api.app.tutor.service``).

``POST /v1/tutor/ask/stream`` does the same work but answers with Server-Sent
Events: ``status`` (``retrieving``, ``reading_image``, ``remembering``,
``answering``, ``web_research``, ``judging``), ``draft`` operations while the
answer is written (unverified, never stored, replaced by the final answer),
then ``answer`` (the JSON route's body) and ``done``. Failures arrive as one
``error`` event carrying the JSON route's status code (404, 429, 502, 503).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.api.library import get_store
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import set_database_tenant
from apps.api.app.observability import logger
from apps.api.app.ops.ratelimit import rate_limit
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from apps.api.app.tutor import images, repo, service
from apps.api.app.tutor.contracts import (
    AskRequest,
    AskResponse,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
)
from apps.api.app.tutor.service import lexical_query
from apps.api.app.tutor.stream import (
    SSE_HEADERS,
    Finished,
    error_event,
    progress_event,
    sse,
    status_event,
    with_progress,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from packages.library.storage import ObjectStore
from packages.models.claude_code import ClaudeCodeTransport, ModelCallError, UsageLimitError
from packages.models.gateway import Transport
from packages.tutor.models import JudgeStats, Segment
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["lexical_query", "router"]

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/tutor", tags=["tutor"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
UNAVAILABLE = ("The tutor is unavailable: the Claude Code CLI is not installed on the "
               "API server, so no model can be called.")


def model_transport() -> Transport | None:
    """The production model transport, or None when the CLI is absent; tests override."""
    transport = ClaudeCodeTransport(get_settings().claude_code_bin)
    return transport if transport.available() else None


def tutor_store() -> ObjectStore:
    """Private object storage for attached images; tests override."""
    return get_store()


OptionalTransportDep = Annotated[Transport | None, Depends(model_transport)]
StoreDep = Annotated[ObjectStore, Depends(tutor_store)]
TUTOR_LIMIT = Depends(rate_limit("tutor", principal_context))
UPLOAD_LIMIT = Depends(rate_limit("upload", principal_context))


def get_transport(transport: OptionalTransportDep) -> Transport:
    if transport is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    return transport


TransportDep = Annotated[Transport, Depends(get_transport)]


def _model_error(exc: ModelCallError) -> HTTPException:
    logger.warning("tutor_model_failed", extra={"error_type": type(exc).__name__})
    if isinstance(exc, UsageLimitError):
        return HTTPException(status_code=429, detail="The model usage window is exhausted; "
                             "try the tutor again later.")
    return HTTPException(status_code=502, detail="The tutor model call failed; try again.")


async def _loaded(
    session: AsyncSession, principal: Principal, body: AskRequest
) -> service.Loaded:
    loaded = await service.load(session, principal, body)
    if service.needs_reading(loaded):
        await session.rollback()  # the vision call must not hold a transaction open
    return loaded


@router.post("/ask", response_model=AskResponse, dependencies=[TUTOR_LIMIT])
async def ask(
    body: AskRequest, principal: PrincipalDep, session: SessionDep, transport: TransportDep,
    store: StoreDep,
) -> AskResponse:
    loaded = await _loaded(session, principal, body)
    try:
        reading = await run_in_threadpool(service.read_attached, transport, store,
                                          principal.tenant_id, loaded)
        if reading[1]:
            await set_database_tenant(session, principal.tenant_id)
        prepared = await service.retrieve(session, principal, body, loaded, reading)
        outcome = await run_in_threadpool(service.answer_work, transport, body, prepared)
    except ModelCallError as exc:
        raise _model_error(exc) from exc
    return await service.persist(session, principal, body, prepared, outcome)


async def _ask_steps(
    body: AskRequest, principal: Principal, session: AsyncSession, transport: Transport,
    store: ObjectStore,
) -> AsyncIterator[str | AskResponse]:
    """SSE frames for one ask, then the stored response; errors propagate."""
    loaded = await _loaded(session, principal, body)
    reading: Any = (None, False)
    if loaded.image is not None:
        work = partial(service.read_attached, transport, store, principal.tenant_id, loaded)
        async for item in with_progress(work):
            if isinstance(item, Finished):
                reading = item.value
            else:
                yield progress_event(item)
        if reading[1]:
            await set_database_tenant(session, principal.tenant_id)
    prepared = await service.retrieve(session, principal, body, loaded, reading)
    drafts = get_settings().tutor_stream_drafts
    outcome: Any = None
    async for item in with_progress(partial(service.answer_work, transport, body, prepared,
                                            drafts)):
        if isinstance(item, Finished):
            outcome = item.value
        else:
            yield progress_event(item)
    if outcome is None:  # defensive: with_progress always finishes or raises
        raise ModelCallError("tutor produced no answer")
    yield await service.persist(session, principal, body, prepared, outcome)


async def _ask_events(
    body: AskRequest, principal: Principal, session: AsyncSession, transport: Transport | None,
    store: ObjectStore,
) -> AsyncIterator[str]:
    if transport is None:
        yield error_event(503, UNAVAILABLE)
        return
    yield status_event("retrieving")
    response: AskResponse | None = None
    try:
        async for step in _ask_steps(body, principal, session, transport, store):
            if isinstance(step, AskResponse):
                response = step
            else:
                yield step
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
    if response is None:
        yield error_event(500, "The tutor failed unexpectedly; try again.")
        return
    yield sse("answer", response.model_dump(mode="json"))
    yield sse("done", {"thread_id": str(response.thread_id),
                       "message_id": str(response.message_id)})


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    dependencies=[TUTOR_LIMIT],
    responses={200: {
        "description": "Server-Sent Events: status* and draft*, then answer + done, "
                       "or one error.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }},
)
async def ask_stream(
    body: AskRequest, principal: PrincipalDep, session: SessionDep,
    transport: OptionalTransportDep, store: StoreDep,
) -> StreamingResponse:
    return StreamingResponse(_ask_events(body, principal, session, transport, store),
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
        image_id=row.get("image_id"),
        image_reading=images.stored_reading(row.get("image_reading")),
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
