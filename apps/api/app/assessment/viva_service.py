"""Viva and staged-case lifecycle for the API: create, answer, end, read.

No model is called here. Creating a viva (or a staged case that needs a new
rubric) stores the session with pending work for the worker; answering a turn
stores the answer and queues its grading. The server owns the clock: an answer
after the deadline is refused and the session is finished from its graded
turns. Enqueueing is the caller's job, after commit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from apps.api.app.assessment import store, viva_evidence, viva_flow, viva_store
from apps.api.app.assessment.viva_contracts import VivaCreate
from apps.api.app.security.principal import Principal
from packages.assessment.grading_jobs import STALE_AFTER
from packages.assessment.staged_case import STAGE_PROMPTS
from sqlalchemy.ext.asyncio import AsyncSession

VectorFor = Callable[[str], Awaitable[Sequence[float] | None]]
REQUEUE_AFTER = timedelta(minutes=10)


class VivaRefused(Exception):
    """A refusal with an HTTP status and a stable, content-free code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


async def _staged_question(
    db: AsyncSession, user_id: UUID, body: VivaCreate
) -> dict[str, Any] | None:
    question_id = body.question_id
    if question_id is None and body.figure_id is not None:
        found = await viva_store.staged_question_for_figure(db, user_id, body.figure_id)
        question_id = found["id"] if found else None
    if question_id is None:
        return None
    question = await store.get_question(db, user_id, question_id)
    if question is None:
        raise VivaRefused(404, "question_not_found")
    if question["type"] != "image_case" or not (question["answer"] or {}).get("stages"):
        raise VivaRefused(422, "question_not_staged")
    if await store.in_open_exam(db, user_id, question_id):
        raise VivaRefused(409, "question_in_open_exam")
    return question


async def _start_staged(
    db: AsyncSession, principal: Principal, base: dict[str, Any], question: dict[str, Any]
) -> UUID:
    stages = question["answer"]["stages"]
    sid = await viva_store.insert_session(db, principal.tenant_id, principal.user_id, {
        **base, "topic": question["topic"], "figure_id": question.get("figure_id"),
        "question_id": question["id"], "scenario": question["stem"], "evidence": [],
        "case_data": {"stages": stages, "scenario_citations": question["citations"]},
        "status": "active", "work": "none"})
    first = stages[0]
    await viva_store.insert_turn(db, principal.tenant_id, principal.user_id, sid, {
        "turn_no": 1, "stage": first["stage"], "level": 1, "move": "stage",
        "prompt": STAGE_PROMPTS[first["stage"]], "expected": first["marking_scheme"]})
    return sid


async def create_session(
    db: AsyncSession, principal: Principal, body: VivaCreate, vector_for: VectorFor,
    now: datetime,
) -> tuple[UUID, bool]:
    """Store a new session; returns (id, whether opening work must be queued)."""
    figure = None
    if body.figure_id is not None:
        figure = await viva_evidence.load_figure(db, principal.user_id, body.figure_id)
        if figure is None:
            raise VivaRefused(404, "figure_not_found")
    minutes = body.time_limit_minutes
    base: dict[str, Any] = {
        "kind": body.kind, "style": body.style, "topic": body.topic or "",
        "max_turns": body.turn_limit(), "started_at": now,
        "deadline_at": now + timedelta(minutes=minutes) if minutes else None,
    }
    if body.kind == "image_case":
        question = await _staged_question(db, principal.user_id, body)
        if question is not None:
            return await _start_staged(db, principal, base, question), False
    query = viva_evidence.search_query(body.topic, figure)
    vector = await vector_for(query) if query else None
    excerpts = await viva_evidence.gather(db, principal.user_id, body.topic, figure, vector,
                                          body.kind == "image_case",
                                          tenant_id=principal.tenant_id)
    if not viva_evidence.has_text(excerpts):
        raise VivaRefused(422, "no_source_material")
    figure_id = next((e.figure_id for e in excerpts if e.figure_id), None)
    if body.kind == "image_case" and figure_id is None:
        raise VivaRefused(422, "no_described_figure")
    sid = await viva_store.insert_session(db, principal.tenant_id, principal.user_id, {
        **base, "figure_id": figure_id, "evidence": viva_evidence.freeze(excerpts),
        "status": "preparing", "work": "pending"})
    return sid, True


async def _locked(db: AsyncSession, principal: Principal, sid: UUID) -> dict[str, Any]:
    row = await viva_store.load_session(db, principal.user_id, sid, lock=True)
    if row is None:
        raise VivaRefused(404, "viva_not_found")
    return row


def _expired(row: dict[str, Any], now: datetime) -> bool:
    return row["deadline_at"] is not None and now >= row["deadline_at"]


async def submit_answer(
    db: AsyncSession, principal: Principal, sid: UUID, turn_no: int, answer: str,
    now: datetime,
) -> bool:
    """Store the answer and queue grading; False means time ran out (session finished)."""
    row = await _locked(db, principal, sid)
    if row["status"] != "active":
        raise VivaRefused(409, "viva_not_active")
    if row["work"] != "none":
        raise VivaRefused(409, "viva_examiner_busy")
    if _expired(row, now):
        await viva_flow.finish(db, row, "time_up", now)
        return False
    if not await viva_store.answer_turn(db, sid, turn_no, answer, now):
        raise VivaRefused(409, "viva_turn_closed")
    await viva_flow.request_work(db, sid, turn_no)
    return True


async def end_session(db: AsyncSession, principal: Principal, sid: UUID, now: datetime) -> None:
    """End early; idempotent. Work in flight is discarded when it returns."""
    row = await _locked(db, principal, sid)
    if row["status"] not in ("finished", "failed"):
        await viva_flow.finish(db, row, "ended_by_candidate", now)


async def refresh(
    db: AsyncSession, principal: Principal, sid: UUID, now: datetime
) -> tuple[dict[str, Any], int | None]:
    """Finish a session whose deadline passed while idle; find stale work to re-queue."""
    row = await viva_store.load_session(db, principal.user_id, sid)
    if row is None:
        raise VivaRefused(404, "viva_not_found")
    if row["status"] == "active" and row["work"] == "none" and _expired(row, now):
        row = await _locked(db, principal, sid)
        if row["status"] == "active" and row["work"] == "none":
            await viva_flow.finish(db, row, "time_up", now)
    requeue = None
    if row["work"] != "none":
        requeue = await viva_store.touch_stale_work(
            db, principal.user_id, sid, now - REQUEUE_AFTER, now - STALE_AFTER)
    fresh = await viva_store.load_session(db, principal.user_id, sid)
    return fresh or row, requeue
