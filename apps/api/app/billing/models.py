"""Billing value types, the plan catalogue, and event-to-status mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

# Plan catalogue. PLACEHOLDER values: billing is parked (ADR 0011) and these
# numbers are not an owner pricing decision. Replace them only through an ADR
# that records the owner's approved catalogue.
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
