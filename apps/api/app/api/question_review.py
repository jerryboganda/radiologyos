"""Draft review queue and item statistics for the owner's question bank."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.app.api.assessment import PrincipalDep, SessionDep
from apps.api.app.assessment import item_stats, review, review_store, store
from apps.api.app.assessment.review_contracts import (
    ReviewItem,
    ReviewRequest,
    ReviewResponse,
    StatsRecomputeResponse,
    review_item,
)
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/v1", tags=["assessment"])


@router.get("/questions/review", response_model=list[ReviewItem])
async def review_queue(
    principal: PrincipalDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[ReviewItem]:
    rows = await review_store.list_drafts(session, principal.user_id, limit, offset)
    return [review_item(row) for row in rows]


@router.post("/questions/stats/recompute", response_model=StatsRecomputeResponse)
async def recompute_stats(principal: PrincipalDep, session: SessionDep) -> StatsRecomputeResponse:
    outcome = await item_stats.recompute(session, principal.tenant_id, principal.user_id)
    await session.commit()
    return StatsRecomputeResponse.model_validate(outcome)


@router.post("/questions/{question_id}/review", response_model=ReviewResponse)
async def review_question(
    question_id: UUID, body: ReviewRequest, principal: PrincipalDep, session: SessionDep
) -> ReviewResponse:
    question = await review_store.get_for_review(session, principal.user_id, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="question not found")
    # The response carries the key, so it is refused while the item is in an open exam.
    if await store.in_open_exam(session, principal.user_id, question_id):
        raise HTTPException(status_code=409, detail="question is in an open exam")
    try:
        updated = await review.review(session, principal, question, body.action, body.edits())
    except review.ReviewRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    await session.commit()
    return ReviewResponse(action=body.action, status=updated["status"],
                          item=review_item(updated))
