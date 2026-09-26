"""Grade disputes on auto-graded written exam points (ADR 0029).

The exam's owner opens a dispute on one scheme point of a graded written item;
the tenant's owner/admin (``org_admin``/``superadmin``) works the open-dispute
queue and accepts (the score is adjusted and audited) or rejects it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.app.api.assessment import PrincipalDep, SessionDep
from apps.api.app.assessment import dispute_service, dispute_store, exams
from apps.api.app.security.principal import require_roles
from fastapi import APIRouter, HTTPException, Query, status
from packages.assessment.disputes import DisputeRefused
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1", tags=["assessment"])


class DisputeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: UUID
    point_index: int = Field(ge=0, le=99, description="0-based index of the scheme point")
    reason: str = Field(min_length=1, max_length=2000)


class DisputeView(BaseModel):
    id: UUID
    exam_id: UUID
    question_id: UUID
    point_index: int
    reason: str
    marks: float
    awarded_before: float
    awarded_after: float | None
    status: Literal["open", "accepted", "rejected"]
    resolution_note: str
    created_at: datetime
    resolved_at: datetime | None


class DisputeQueueItem(DisputeView):
    user_id: UUID
    stem: str
    topic: str
    point: str
    justification: str
    answer_text: str
    model_answer: str
    citations: list[dict[str, Any]]


class DisputeResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "reject"]
    awarded: float | None = Field(
        default=None, ge=0, le=10,
        description="Accept: the new award for the point (default: its full marks).")
    note: str = Field(default="", max_length=2000)


class DisputeResolved(BaseModel):
    dispute: DisputeView
    exam_score: float | None = None
    exam_percent: float | None = None


def _refused(exc: DisputeRefused) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.code)


@router.post("/exams/{exam_id}/disputes", response_model=DisputeView,
             status_code=status.HTTP_201_CREATED)
async def open_dispute(
    exam_id: UUID, body: DisputeCreate, principal: PrincipalDep, session: SessionDep
) -> DisputeView:
    try:
        row = await dispute_service.open_dispute(
            session, principal, exam_id, body.question_id, body.point_index, body.reason)
    except DisputeRefused as exc:
        raise _refused(exc) from exc
    await session.commit()
    return DisputeView.model_validate(row)


@router.get("/exams/{exam_id}/disputes", response_model=list[DisputeView])
async def exam_disputes(
    exam_id: UUID, principal: PrincipalDep, session: SessionDep
) -> list[DisputeView]:
    if await exams.load_exam(session, principal.user_id, exam_id) is None:
        raise HTTPException(status_code=404, detail="exam not found")
    rows = await dispute_store.list_for_exam(session, principal.user_id, exam_id)
    return [DisputeView.model_validate(row) for row in rows]


@router.get("/grade-disputes/review", response_model=list[DisputeQueueItem])
async def dispute_queue(
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[DisputeQueueItem]:
    """Open disputes of the tenant for the owner/admin."""
    require_roles(principal, *dispute_service.RESOLVER_ROLES)
    rows = await dispute_store.open_queue(session, limit, offset)
    return [DisputeQueueItem.model_validate(dispute_service.queue_entry(row)) for row in rows]


@router.post("/grade-disputes/{dispute_id}/resolve", response_model=DisputeResolved)
async def resolve_dispute(
    dispute_id: UUID, body: DisputeResolve, principal: PrincipalDep, session: SessionDep
) -> DisputeResolved:
    require_roles(principal, *dispute_service.RESOLVER_ROLES)
    try:
        row, result = await dispute_service.resolve_dispute(
            session, principal, dispute_id, body.action, body.awarded, body.note)
    except DisputeRefused as exc:
        raise _refused(exc) from exc
    await session.commit()
    return DisputeResolved(dispute=DisputeView.model_validate(row),
                           exam_score=(result or {}).get("score"),
                           exam_percent=(result or {}).get("percent"))
