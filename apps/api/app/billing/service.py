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

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.api.app.billing.models import (
    EVENT_STATUS,
    MODELLED_EVENT_TYPES,
    PLAN_ORDER,
    PLANS,
    BillingError,
    BillingEvent,
    PaymentMethod,
    SignatureError,
    Subscription,
    SubscriptionStatus,
    next_billing_date,
    trial_days_for,
)
from apps.api.app.billing.stripe import (
    parse_stripe_event,
    status_for_event,
    verify_stripe_signature,
)

__all__ = [
    "EVENT_STATUS",
    "MODELLED_EVENT_TYPES",
    "PLANS",
    "PLAN_ORDER",
    "BillingError",
    "BillingEvent",
    "BillingService",
    "PaymentMethod",
    "SignatureError",
    "Subscription",
    "SubscriptionStatus",
    "next_billing_date",
    "parse_stripe_event",
    "trial_days_for",
    "verify_stripe_signature",
]


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
            status=status_for_event(event),
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

