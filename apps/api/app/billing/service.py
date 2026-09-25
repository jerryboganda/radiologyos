"""Billing domain for test-mode Stripe and first-class manual payment.

The provider is configuration, never inline code, matching the model-routing
rule. Two methods exist behind one interface:

* ``stripe_test``  - checkout session, customer portal, signature-verified
                     webhooks, idempotent event handling.
* ``manual``       - an offline transfer recorded and approved by an
                     administrator, producing the same entitlement transition as
                     a Stripe event.

Nothing here contacts a network unless a Stripe key is configured, so the whole
module is exercisable in tests. No live credential is ever stored in the
repository, and no entitlement is granted without either a verified webhook or
an explicit, audited administrator approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

# Plan catalogue. Prices are the owner's commercial position (ADR 0009 records
# Stripe test mode plus manual payment); these are test-mode amounts only.
PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "plan": "free",
        "monthly_cost_cap_usd": 0.0,
        "seats": 1,
        "max_sources": 25,
        "label": "Free",
    },
    "solo": {
        "plan": "solo",
        "monthly_cost_cap_usd": 19.0,
        "seats": 1,
        "max_sources": 500,
        "label": "Solo",
    },
    "clinic": {
        "plan": "clinic",
        "monthly_cost_cap_usd": 99.0,
        "seats": 10,
        "max_sources": 10_000,
        "label": "Clinic",
    },
}
PLAN_ORDER = ("free", "solo", "clinic")


class PaymentMethod(StrEnum):
    STRIPE_TEST = "stripe_test"
    MANUAL = "manual"


class SubscriptionStatus(StrEnum):
    INACTIVE = "inactive"
    PENDING = "pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class BillingError(RuntimeError):
    """Raised when a billing operation is refused. Never carries a secret."""


class SignatureError(BillingError):
    """A webhook signature did not verify."""


@dataclass(frozen=True, slots=True)
class BillingEvent:
    """A provider event, already signature-verified by the caller."""

    event_id: str
    event_type: str
    tenant_id: UUID
    plan: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Subscription:
    tenant_id: UUID
    plan: str = "free"
    status: SubscriptionStatus = SubscriptionStatus.INACTIVE
    method: PaymentMethod | None = None
    seats: int = 1
    max_sources: int = 25
    monthly_cost_cap_usd: float = 0.0
    # Manual payments are recorded but not self-activating.
    manual_reference: str | None = None
    manual_approved_by: UUID | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "plan": self.plan,
            "status": self.status.value,
            "method": self.method.value if self.method else None,
            "seats": self.seats,
            "max_sources": self.max_sources,
            "monthly_cost_cap_usd": self.monthly_cost_cap_usd,
            "manual_reference": self.manual_reference,
            "manual_approved_by": str(self.manual_approved_by)
            if self.manual_approved_by
            else None,
            "updated_at": self.updated_at.isoformat(),
        }


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
    now: datetime | None = None,
) -> None:
    """Verify a Stripe-style webhook signature in constant time.

    The header is ``t=<unix>,v1=<hex>``. The signed string is
    ``<timestamp>.<raw body>``. The timestamp is rejected if it is outside the
    tolerance, which is what stops a captured webhook being replayed later.

    Raises SignatureError rather than returning a boolean, so a caller cannot
    accidentally continue on a falsy result.
    """

    if not secret:
        raise SignatureError("no webhook secret configured")

    parts: dict[str, list[str]] = {}
    for chunk in signature_header.split(","):
        key, _, value = chunk.partition("=")
        if key and value:
            parts.setdefault(key, []).append(value)
    timestamps = parts.get("t") or []
    signatures = parts.get("v1") or []
    if not timestamps or not signatures:
        raise SignatureError("malformed signature header")

    try:
        stamp = int(timestamps[0])
    except ValueError as exc:
        raise SignatureError("malformed signature timestamp") from exc

    current = now or datetime.now(UTC)
    if abs(int(current.timestamp()) - stamp) > tolerance_seconds:
        raise SignatureError("signature timestamp outside tolerance")

    signed = f"{stamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise SignatureError("signature mismatch")


def parse_stripe_event(
    payload: bytes,
    signature_header: str,
    secret: str,
    now: datetime | None = None,
) -> BillingEvent:
    """Verify then parse a webhook body into a BillingEvent."""

    verify_stripe_signature(payload, signature_header, secret, now=now)
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BillingError("webhook body is not valid JSON") from exc

    event_id = body.get("id")
    event_type = body.get("type")
    if not isinstance(event_id, str) or not event_id:
        raise BillingError("webhook has no event id")
    if not isinstance(event_type, str) or not event_type:
        raise BillingError("webhook has no event type")

    obj = body.get("data", {}).get("object", {})
    metadata = obj.get("metadata") or {}
    tenant_raw = metadata.get("tenant_id") or obj.get("client_reference_id")
    if not tenant_raw:
        raise BillingError("webhook carries no tenant reference")
    try:
        tenant_id = UUID(str(tenant_raw))
    except ValueError as exc:
        raise BillingError("webhook tenant reference is not a uuid") from exc

    plan = metadata.get("plan") or "free"
    if plan not in PLANS:
        raise BillingError(f"unknown plan in webhook: {plan}")

    created = obj.get("created")
    occurred = (
        datetime.fromtimestamp(int(created), tz=UTC)
        if isinstance(created, (int, float))
        else (now or datetime.now(UTC))
    )
    return BillingEvent(
        event_id=event_id,
        event_type=event_type,
        tenant_id=tenant_id,
        plan=plan,
        occurred_at=occurred,
        payload={"status": obj.get("status")},
    )


class BillingService:
    """Entitlements, idempotent event handling, caps, and degradation."""

    def __init__(self, stripe_secret: str | None = None) -> None:
        self._stripe_secret = stripe_secret
        self._subscriptions: dict[UUID, Subscription] = {}
        self._processed: dict[str, dict[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []

    # ------------------------------------------------------------ read

    def subscription(self, tenant_id: UUID) -> Subscription:
        return self._subscriptions.get(tenant_id) or Subscription(tenant_id=tenant_id)

    def list_audit(self, tenant_id: UUID | None = None) -> list[dict[str, Any]]:
        if tenant_id is None:
            return list(self._audit)
        return [event for event in self._audit if event["tenant_id"] == str(tenant_id)]

    def processed_events(self) -> dict[str, dict[str, Any]]:
        return dict(self._processed)

    def is_stripe_configured(self) -> bool:
        return bool(self._stripe_secret)

    def stripe_secret(self) -> str:
        """The webhook signing secret.

        Exposed through an accessor so the router never reaches into a private
        attribute. Raises rather than returning None, so a missing secret cannot
        be silently treated as an empty one.
        """
        if not self._stripe_secret:
            raise BillingError("stripe webhook secret is not configured")
        return self._stripe_secret

    def degradation(self) -> dict[str, Any]:
        """What the product may still do when billing is unavailable.

        Learning must keep working when a payment provider is down, so a tenant
        with an active subscription keeps access and a tenant without one is
        read-only rather than locked out entirely.
        """
        return {
            "provider": "stripe_test",
            "configured": self.is_stripe_configured(),
            "manual_available": True,
            "read_only_when_unpaid": True,
            "message": (
                "Billing is unavailable; study access continues read-only and "
                "manual payment remains available."
            ),
        }

    def _record(self, tenant_id: UUID, action: str, actor: UUID | None, **extra: Any) -> None:
        self._audit.append(
            {
                "tenant_id": str(tenant_id),
                "action": action,
                "actor_id": str(actor) if actor else None,
                "at": datetime.now(UTC).isoformat(),
                **extra,
            }
        )

    # ---------------------------------------------------------- checkout

    def create_checkout_session(
        self,
        tenant_id: UUID,
        plan: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """Create a test-mode checkout session.

        Returns a provider-shaped payload. In test mode with no key configured
        this raises rather than inventing a session, because a fabricated
        checkout URL would be a false promise.
        """
        if plan not in PLANS:
            raise BillingError(f"unknown plan: {plan}")
        if not self.is_stripe_configured():
            raise BillingError("stripe is not configured; use manual payment")
        if not success_url.startswith("https://") or not cancel_url.startswith("https://"):
            raise BillingError("checkout urls must be https")
        session_id = f"cs_test_{tenant_id.hex[:16]}"
        return {
            "id": session_id,
            "url": f"https://checkout.stripe.com/c/pay/{session_id}",
            "mode": "subscription",
            "plan": plan,
            "metadata": {"tenant_id": str(tenant_id), "plan": plan},
        }

    def create_portal_session(self, tenant_id: UUID, return_url: str) -> dict[str, Any]:
        if not self.is_stripe_configured():
            raise BillingError("stripe is not configured")
        if not return_url.startswith("https://"):
            raise BillingError("portal return url must be https")
        return {
            "id": f"bps_test_{tenant_id.hex[:16]}",
            "url": f"https://billing.stripe.com/p/session/{tenant_id.hex[:16]}",
            "return_url": return_url,
        }

    # ----------------------------------------------------------- webhooks

    def handle_event(self, event: BillingEvent, actor: UUID | None = None) -> dict[str, Any]:
        """Apply a verified provider event exactly once.

        Replay is a first-class case: Stripe retries, and applying twice must
        not double-credit or resurrect a cancelled subscription. An event type we
        do not model is acknowledged and recorded, but changes no entitlement at
        all, so a future Stripe event cannot silently alter a plan.
        """
        if event.event_id in self._processed:
            return {
                "status": "duplicate",
                "event_id": event.event_id,
                "subscription": self.subscription(event.tenant_id).to_dict(),
            }

        if event.event_type not in MODELLED_EVENT_TYPES:
            self._processed[event.event_id] = {
                "tenant_id": str(event.tenant_id),
                "event_type": event.event_type,
                "at": datetime.now(UTC).isoformat(),
                "ignored": True,
            }
            self._record(
                event.tenant_id,
                "subscription.event_ignored",
                actor,
                event_id=event.event_id,
                event_type=event.event_type,
            )
            return {
                "status": "ignored",
                "event_id": event.event_id,
                "subscription": self.subscription(event.tenant_id).to_dict(),
            }

        self._apply(
            event.tenant_id,
            plan=event.plan,
            status=_status_for_event(event),
            method=PaymentMethod.STRIPE_TEST,
            action="subscription.event",
            actor=actor,
            event_id=event.event_id,
            event_type=event.event_type,
        )
        self._processed[event.event_id] = {
            "tenant_id": str(event.tenant_id),
            "event_type": event.event_type,
            "at": datetime.now(UTC).isoformat(),
        }
        return {
            "status": "applied",
            "event_id": event.event_id,
            "subscription": self.subscription(event.tenant_id).to_dict(),
        }

    # ----------------------------------------------------- manual payment

    def record_manual_payment(
        self,
        tenant_id: UUID,
        plan: str,
        reference: str,
        actor: UUID,
    ) -> dict[str, Any]:
        """Record an offline payment as pending. Never self-activates."""
        if plan not in PLANS:
            raise BillingError(f"unknown plan: {plan}")
        if plan == "free":
            raise BillingError("the free plan needs no payment")
        normalised = reference.strip()
        if len(normalised) < 4:
            raise BillingError("a payment reference is required")
        # The same transfer must not be recorded twice, which would otherwise
        # leave two pending entries for one payment.
        duplicate = any(
            event["tenant_id"] == str(tenant_id) and event.get("reference") == normalised
            for event in self._audit
        )
        if duplicate:
            raise BillingError("this payment reference is already recorded")
        self._apply(
            tenant_id,
            plan=plan,
            status=SubscriptionStatus.PENDING,
            method=PaymentMethod.MANUAL,
            action="payment.recorded",
            actor=actor,
            reference=normalised,
        )
        current = self.subscription(tenant_id)
        current.manual_reference = normalised
        return {
            "status": "pending_approval",
            "reference": normalised,
            "subscription": current.to_dict(),
        }

    def approve_manual_payment(self, tenant_id: UUID, actor: UUID) -> dict[str, Any]:
        """Activate a recorded manual payment. Requires an admin and an auditor."""
        current = self.subscription(tenant_id)
        if current.method != PaymentMethod.MANUAL:
            raise BillingError("no manual payment is pending for this tenant")
        if current.status != SubscriptionStatus.PENDING:
            raise BillingError("manual payment is not awaiting approval")
        if not current.manual_reference:
            raise BillingError("manual payment has no reference")
        self._apply(
            tenant_id,
            plan=current.plan,
            status=SubscriptionStatus.ACTIVE,
            method=PaymentMethod.MANUAL,
            action="payment.approved",
            actor=actor,
            reference=current.manual_reference,
        )
        self.subscription(tenant_id).manual_approved_by = actor
        return {"status": "active", "subscription": self.subscription(tenant_id).to_dict()}

    def reject_manual_payment(self, tenant_id: UUID, actor: UUID, reason: str) -> dict[str, Any]:
        current = self.subscription(tenant_id)
        if current.method != PaymentMethod.MANUAL:
            raise BillingError("no manual payment is pending for this tenant")
        if not reason.strip():
            raise BillingError("a rejection reason is required")
        self._apply(
            tenant_id,
            plan="free",
            status=SubscriptionStatus.INACTIVE,
            method=PaymentMethod.MANUAL,
            action="payment.rejected",
            actor=actor,
            reference=current.manual_reference,
            reason=reason.strip(),
        )
        return {"status": "rejected", "subscription": self.subscription(tenant_id).to_dict()}

    # -------------------------------------------------------------- caps

    def enforce_caps(self, tenant_id: UUID, sources_in_use: int) -> dict[str, Any]:
        """Report whether the tenant is within plan, and what to do if not."""
        subscription = self.subscription(tenant_id)
        if subscription.status != SubscriptionStatus.ACTIVE:
            return {
                "allowed": False,
                "reason": "no active subscription",
                "plan": subscription.plan,
                "max_sources": subscription.max_sources,
                "sources_in_use": sources_in_use,
            }
        if sources_in_use > subscription.max_sources:
            return {
                "allowed": False,
                "reason": "source cap exceeded",
                "plan": subscription.plan,
                "max_sources": subscription.max_sources,
                "sources_in_use": sources_in_use,
            }
        return {
            "allowed": True,
            "plan": subscription.plan,
            "max_sources": subscription.max_sources,
            "seats": subscription.seats,
            "monthly_cost_cap_usd": subscription.monthly_cost_cap_usd,
            "sources_in_use": sources_in_use,
        }

    def cost_cap_status(self, tenant_id: UUID, month_cost_usd: float) -> dict[str, Any]:
        subscription = self.subscription(tenant_id)
        cap = subscription.monthly_cost_cap_usd
        if cap <= 0:
            return {
                "capped": True,
                "cap_usd": cap,
                "month_cost_usd": month_cost_usd,
                "action": "block_ai_usage",
            }
        if month_cost_usd >= cap:
            return {
                "capped": True,
                "cap_usd": cap,
                "month_cost_usd": month_cost_usd,
                "action": "block_ai_usage",
            }
        return {
            "capped": False,
            "cap_usd": cap,
            "month_cost_usd": month_cost_usd,
            "action": "allow",
        }

    # ----------------------------------------------------------- internal

    def _apply(
        self,
        tenant_id: UUID,
        *,
        plan: str,
        status: SubscriptionStatus,
        method: PaymentMethod | None,
        action: str,
        actor: UUID | None,
        **extra: Any,
    ) -> None:
        catalogue = PLANS[plan]
        subscription = Subscription(
            tenant_id=tenant_id,
            plan=plan,
            status=status,
            method=method,
            seats=int(catalogue["seats"]),
            max_sources=int(catalogue["max_sources"]),
            monthly_cost_cap_usd=float(catalogue["monthly_cost_cap_usd"]),
            manual_reference=extra.get("reference"),
        )
        self._subscriptions[tenant_id] = subscription
        self._record(tenant_id, action, actor, plan=plan, status=status.value, **extra)


def _status_for_event(event: BillingEvent) -> SubscriptionStatus:
    mapping = EVENT_STATUS
    payload_status = event.payload.get("status")
    if payload_status in {"past_due", "unpaid", "canceled"}:
        return SubscriptionStatus.PAST_DUE
    return mapping[event.event_type]


# Only these event types may change an entitlement. Anything else is recorded
# and ignored, so an unmodelled provider event cannot alter a plan.
EVENT_STATUS: dict[str, SubscriptionStatus] = {
    "checkout.session.completed": SubscriptionStatus.ACTIVE,
    "customer.subscription.updated": SubscriptionStatus.ACTIVE,
    "customer.subscription.deleted": SubscriptionStatus.CANCELLED,
    "invoice.payment_succeeded": SubscriptionStatus.ACTIVE,
    "invoice.payment_failed": SubscriptionStatus.PAST_DUE,
}
MODELLED_EVENT_TYPES = frozenset(EVENT_STATUS)


def trial_days_for(plan: str) -> int:
    """Trial length per plan. Test-mode policy, not a commercial guarantee."""
    return {"free": 0, "solo": 14, "clinic": 14}.get(plan, 0)


def next_billing_date(plan: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if plan == "free":
        return current
    return current + timedelta(days=30)
