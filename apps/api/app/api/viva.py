"""Viva examiner and staged image-case routes (ADR 0026).

A session is a multi-turn viva on a topic or figure, or a staged TOACS image
case. Model work (opening, grading each answer, the next examiner question,
the staged rubric) runs in the worker, keyed by (session, turn,
``PIPELINE_VERSION``); these routes store answers, enqueue after commit, and
serve the transcript. The web page polls ``GET /v1/viva/sessions/{id}`` while
``work`` is not ``none``. Reading a session re-queues work untouched for ten
minutes and finishes a session whose deadline passed while it was idle.
Transcripts, answers, and prompts are never logged.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.app.api.assessment import PrincipalDep, SessionDep
from apps.api.app.api.library import query_vector
from apps.api.app.assessment import viva_service, viva_store
from apps.api.app.assessment.viva_contracts import (
    SessionSummary,
    SessionView,
    VivaAnswer,
    VivaCreate,
    session_summary,
    session_view,
)
from apps.api.app.assessment.viva_flow import enqueue_step
from apps.api.app.assessment.viva_service import VivaRefused
from apps.api.app.core.time import now_utc
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/v1/viva", tags=["viva"])
TurnNo = Annotated[int, Path(ge=1, le=40)]


def _refused(exc: VivaRefused) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.code)


async def _view(db: AsyncSession, principal: Principal, sid: UUID) -> SessionView:
    row = await viva_store.load_session(db, principal.user_id, sid)
    if row is None:
        raise HTTPException(status_code=404, detail="viva_not_found")
    turns = await viva_store.load_turns(db, sid)
    return session_view(row, turns, now_utc())


@router.post("/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: VivaCreate, principal: PrincipalDep, session: SessionDep
) -> SessionView:
    async def vector_for(query: str) -> list[float] | None:
        return await query_vector(principal.tenant_id, query)

    try:
        sid, queue = await viva_service.create_session(
            session, principal, body, vector_for, now_utc())
    except VivaRefused as exc:
        raise _refused(exc) from exc
    view = await _view(session, principal, sid)
    await session.commit()
    if queue:
        enqueue_step(principal.tenant_id, sid, 0)
    return view


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    principal: PrincipalDep, session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[SessionSummary]:
    rows = await viva_store.list_sessions(session, principal.user_id, limit)
    return [session_summary(row) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: UUID, principal: PrincipalDep,
                      session: SessionDep) -> SessionView:
    try:
        _, requeue = await viva_service.refresh(session, principal, session_id, now_utc())
    except VivaRefused as exc:
        raise _refused(exc) from exc
    view = await _view(session, principal, session_id)
    await session.commit()
    if requeue is not None:
        enqueue_step(principal.tenant_id, session_id, requeue)
    return view


@router.post("/sessions/{session_id}/turns/{turn_no}/answer", response_model=SessionView)
async def answer_turn(
    session_id: UUID, turn_no: TurnNo, body: VivaAnswer, principal: PrincipalDep,
    session: SessionDep,
) -> SessionView:
    try:
        accepted = await viva_service.submit_answer(
            session, principal, session_id, turn_no, body.answer_text, now_utc())
    except VivaRefused as exc:
        raise _refused(exc) from exc
    view = await _view(session, principal, session_id)
    await session.commit()
    if not accepted:
        raise HTTPException(status_code=409, detail="viva_time_expired")
    enqueue_step(principal.tenant_id, session_id, turn_no)
    return view


@router.post("/sessions/{session_id}/end", response_model=SessionView)
async def end_session(session_id: UUID, principal: PrincipalDep,
                      session: SessionDep) -> SessionView:
    try:
        await viva_service.end_session(session, principal, session_id, now_utc())
    except VivaRefused as exc:
        raise _refused(exc) from exc
    view = await _view(session, principal, session_id)
    await session.commit()
    return view
