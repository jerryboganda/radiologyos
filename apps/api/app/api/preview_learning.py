from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from apps.api.app.api.preview import preview_principal_context
from apps.api.app.preview.contracts import (
    PreviewCardResponse,
    PreviewMasteryResponse,
    PreviewOnboardingRequest,
    PreviewPlanResponse,
    PreviewReviewRequest,
    PreviewTodayResponse,
)
from apps.api.app.preview.learning import (
    create_plan,
    due_cards,
    get_plan,
    mastery,
    replan,
    review_card,
    today,
)
from apps.api.app.preview.service import get_preview_state, require_preview
from apps.api.app.preview.state import PreviewCard
from apps.api.app.schemas.common import Citation
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(
    prefix="/v1/preview",
    tags=["preview: non-release"],
    dependencies=[Depends(require_preview)],
)


def _card_response(card: PreviewCard) -> PreviewCardResponse:
    return PreviewCardResponse(
        id=str(card.id),
        prompt=card.prompt,
        citation=Citation.model_validate(card.citation),
        due_at=card.due_at,
    )


@router.post("/onboarding", response_model=PreviewPlanResponse)
def onboard(
    payload: PreviewOnboardingRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewPlanResponse:
    if payload.exam_date < date.today():
        raise HTTPException(status_code=422, detail="exam date must be today or later")
    plan = create_plan(
        get_preview_state(),
        principal.tenant_id,
        principal.user_id,
        payload.exam_date,
        payload.hours_per_week,
        payload.session_minutes,
    )
    return PreviewPlanResponse.model_validate(plan)


@router.get("/plan", response_model=PreviewPlanResponse)
def plan(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewPlanResponse:
    current = get_plan(get_preview_state(), principal.tenant_id, principal.user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="onboarding required")
    return PreviewPlanResponse.model_validate(current)


@router.post("/plan/replan", response_model=PreviewPlanResponse)
def regenerate_plan(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewPlanResponse:
    try:
        return PreviewPlanResponse.model_validate(
            replan(get_preview_state(), principal.tenant_id, principal.user_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/today", response_model=PreviewTodayResponse)
def today_bundle(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewTodayResponse:
    try:
        return PreviewTodayResponse.model_validate(
            today(get_preview_state(), principal.tenant_id, principal.user_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cards/due", response_model=tuple[PreviewCardResponse, ...])
def cards_due(
    principal: Annotated[Principal, Depends(preview_principal_context)],
    limit: int = 10,
) -> tuple[PreviewCardResponse, ...]:
    if not 1 <= limit <= 20:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
    cards = due_cards(get_preview_state(), principal.tenant_id, principal.user_id, limit)
    return tuple(_card_response(card) for card in cards)


@router.post("/cards/{card_id}/review", response_model=PreviewCardResponse)
def review(
    card_id: UUID,
    payload: PreviewReviewRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewCardResponse:
    try:
        card = review_card(
            get_preview_state(),
            principal.tenant_id,
            principal.user_id,
            card_id,
            payload.rating,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _card_response(card)


@router.get("/mastery", response_model=PreviewMasteryResponse)
def mastery_view(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewMasteryResponse:
    return PreviewMasteryResponse.model_validate(
        mastery(get_preview_state(), principal.tenant_id, principal.user_id)
    )
