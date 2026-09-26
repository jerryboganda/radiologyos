"""Billing API: Stripe test-mode checkout and portal, manual payment approval."""

from __future__ import annotations

from typing import Annotated, Any

from apps.api.app.billing.service import (
    PLANS,
    BillingError,
    BillingService,
    PaymentMethod,
    SignatureError,
    SubscriptionStatus,
    parse_stripe_event,
)
from apps.api.app.core.config import get_settings
from apps.api.app.security.context import build_shared_dependencies
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

# Built from the shared module, not from `main`, so importing this router can
# never create a cycle back through the app module.
principal_from_request, principal_context = build_shared_dependencies()

def require_billing() -> None:
    # ADR 0011: billing is parked. The routes exist but answer 404 until the
    # owner turns billing on, so no placeholder plan or payment path is live.
    if not get_settings().billing_enabled:
        raise HTTPException(status_code=404, detail="billing is disabled")


router = APIRouter(
    prefix="/v1/billing", tags=["billing"], dependencies=[Depends(require_billing)]
)

_service: BillingService | None = None


def get_billing_service() -> BillingService:
    global _service
    if _service is None:
        _service = BillingService(stripe_secret=None)
    return _service


def reset_billing_service() -> None:
    global _service
    _service = None


def set_billing_service(service: BillingService) -> None:
    global _service
    _service = service


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str
    label: str
    monthly_cost_cap_usd: float
    seats: int
    max_sources: int


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    plan: str
    status: str
    method: str | None
    seats: int
    max_sources: int
    monthly_cost_cap_usd: float
    manual_reference: str | None
    manual_approved_by: str | None
    updated_at: str


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str
    success_url: str
    cancel_url: str


class PortalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    url: str


class ManualPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: str = Field(min_length=1)
    reference: str = Field(min_length=4, max_length=120)


class ManualDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=400)


class BillingResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    subscription: SubscriptionResponse | None = None
    event_id: str | None = None
    reason: str | None = None


class DegradationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    configured: bool
    manual_available: bool
    read_only_when_unpaid: bool
    message: str


def _subscription_payload(principal: Principal, service: BillingService) -> SubscriptionResponse:
    return SubscriptionResponse.model_validate(
        service.subscription(principal.tenant_id).to_dict()
    )


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    _principal: Annotated[Principal, Depends(principal_context)],
) -> list[PlanResponse]:
    return [PlanResponse.model_validate(plan) for plan in PLANS.values()]


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> SubscriptionResponse:
    return _subscription_payload(principal, service)


@router.get("/degradation", response_model=DegradationResponse)
async def billing_degradation(
    _principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> DegradationResponse:
    return DegradationResponse.model_validate(service.degradation())


@router.post("/checkout", response_model=SessionResponse)
async def create_checkout(
    payload: CheckoutRequest,
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> SessionResponse:
    try:
        session = service.create_checkout_session(
            principal.tenant_id, payload.plan, payload.success_url, payload.cancel_url
        )
    except BillingError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return SessionResponse(id=session["id"], url=session["url"])


@router.post("/portal", response_model=SessionResponse)
async def create_portal(
    payload: PortalRequest,
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> SessionResponse:
    try:
        session = service.create_portal_session(principal.tenant_id, payload.return_url)
    except BillingError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return SessionResponse(id=session["id"], url=session["url"])


@router.post("/manual/record", response_model=BillingResultResponse)
async def record_manual(
    payload: ManualPaymentRequest,
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingResultResponse:
    try:
        result = service.record_manual_payment(
            principal.tenant_id, payload.plan, payload.reference, principal.user_id
        )
    except BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BillingResultResponse(
        status=str(result["status"]),
        subscription=SubscriptionResponse.model_validate(result["subscription"]),
    )


@router.post("/manual/approve", response_model=BillingResultResponse)
async def approve_manual(
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingResultResponse:
    require_roles(principal, "org_admin", "superadmin")
    try:
        result = service.approve_manual_payment(principal.tenant_id, principal.user_id)
    except BillingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BillingResultResponse(
        status=str(result["status"]),
        subscription=SubscriptionResponse.model_validate(result["subscription"]),
    )


@router.post("/manual/reject", response_model=BillingResultResponse)
async def reject_manual(
    payload: ManualDecisionRequest,
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingResultResponse:
    require_roles(principal, "org_admin", "superadmin")
    try:
        result = service.reject_manual_payment(
            principal.tenant_id, principal.user_id, payload.reason
        )
    except BillingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BillingResultResponse(
        status=str(result["status"]),
        subscription=SubscriptionResponse.model_validate(result["subscription"]),
    )


@router.post("/webhook/stripe", response_model=BillingResultResponse)
async def stripe_webhook(
    request: Request,
    service: Annotated[BillingService, Depends(get_billing_service)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> BillingResultResponse:
    """Accept a Stripe webhook.

    No principal is resolved: the caller is the provider, authenticated by
    signature. An unverified body must never reach the entitlement path.
    """

    body = await request.body()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="missing Stripe-Signature")
    if not service.is_stripe_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="stripe is not configured on this deployment",
        )
    try:
        event = parse_stripe_event(body, stripe_signature, service.stripe_secret())
    except SignatureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = service.handle_event(event)
    return BillingResultResponse(
        status=str(result["status"]),
        event_id=result.get("event_id"),
        subscription=SubscriptionResponse.model_validate(result["subscription"])
        if result.get("subscription")
        else None,
    )


@router.get("/audit", response_model=list[dict[str, Any]])
async def billing_audit(
    principal: Annotated[Principal, Depends(principal_context)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> list[dict[str, Any]]:
    require_roles(principal, "org_admin", "superadmin")
    return service.list_audit(principal.tenant_id)


__all__ = [
    "BillingService",
    "PaymentMethod",
    "SubscriptionStatus",
    "get_billing_service",
    "reset_billing_service",
    "router",
    "set_billing_service",
]
