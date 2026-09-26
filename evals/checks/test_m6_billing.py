"""M6 eval gate: billing for Stripe test mode and manual payment.

Covers slice T of the A-Z queue, now unblocked by ADR 0009:
  T  Stripe test-mode checkout and portal, signature-verified webhooks,
     idempotent replay, plan caps, cost-cap degradation, and manual payment
     as a first-class method with audited administrator approval

No network call is made: the whole surface is exercised without a key, and a
missing key is asserted to fail loudly rather than invent a session.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.app.billing.service import (
    PLANS,
    BillingError,
    BillingService,
    PaymentMethod,
    SignatureError,
    SubscriptionStatus,
    parse_stripe_event,
    verify_stripe_signature,
)
from evals.checks._billing_support import (
    ADMIN,
    OTHER_TENANT,
    SECRET,
    TENANT,
    enable_billing,
    event_body,
    restore_settings,
    signature,
)


def setup_function() -> None:
    enable_billing()


def teardown_function() -> None:
    restore_settings()


# ------------------------------------------------------- signature safety


def test_a_valid_signature_verifies() -> None:
    payload = event_body()
    verify_stripe_signature(payload, signature(payload), SECRET)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p, s: (p + b" ", s),  # body tampered
        lambda p, s: (p, s.replace("v1=", "v1=0")),  # signature tampered
        lambda p, s: (p, "t=1,v1=deadbeef"),  # forged
    ],
)
def test_tampering_is_rejected(mutate) -> None:  # noqa: ANN001
    payload = event_body()
    body, header = mutate(payload, signature(payload))
    with pytest.raises(SignatureError):
        verify_stripe_signature(body, header, SECRET)


def test_a_replayed_old_timestamp_is_rejected() -> None:
    """Tolerance is what stops a captured webhook being replayed later."""
    payload = event_body()
    old = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
    with pytest.raises(SignatureError, match="tolerance"):
        verify_stripe_signature(payload, signature(payload, stamp=old), SECRET)


def test_an_empty_secret_refuses_everything() -> None:
    payload = event_body()
    with pytest.raises(SignatureError, match="no webhook secret"):
        verify_stripe_signature(payload, signature(payload), "")


@pytest.mark.parametrize("header", ["", "garbage", "t=abc,v1=zz", "v1=abc"])
def test_malformed_headers_are_rejected(header: str) -> None:
    with pytest.raises(SignatureError):
        verify_stripe_signature(event_body(), header, SECRET)


# ------------------------------------------------------------- webhooks


def test_a_verified_event_activates_the_plan() -> None:
    service = BillingService(stripe_secret=SECRET)
    payload = event_body()
    event = parse_stripe_event(payload, signature(payload), SECRET)
    result = service.handle_event(event)

    assert result["status"] == "applied"
    subscription = service.subscription(TENANT)
    assert subscription.plan == "clinic"
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.method == PaymentMethod.STRIPE_TEST
    assert subscription.max_sources == PLANS["clinic"]["max_sources"]


def test_replaying_the_same_event_changes_nothing() -> None:
    """Stripe retries. A replay must not double-credit or resurrect anything."""
    service = BillingService(stripe_secret=SECRET)
    payload = event_body()
    event = parse_stripe_event(payload, signature(payload), SECRET)
    first = service.handle_event(event)
    subscription_after_first = service.subscription(TENANT).to_dict()

    second = service.handle_event(event)

    assert first["status"] == "applied"
    assert second["status"] == "duplicate"
    assert service.subscription(TENANT).to_dict() == subscription_after_first
    assert len(service.processed_events()) == 1


def test_deletion_downgrades_and_is_still_idempotent() -> None:
    service = BillingService(stripe_secret=SECRET)
    active = parse_stripe_event(event_body("evt_a"), signature(event_body("evt_a")), SECRET)
    service.handle_event(active)

    cancel_body = event_body("evt_b", "customer.subscription.deleted")
    cancelled = parse_stripe_event(cancel_body, signature(cancel_body), SECRET)
    service.handle_event(cancelled)
    assert service.subscription(TENANT).status == SubscriptionStatus.CANCELLED

    service.handle_event(cancelled)
    assert service.subscription(TENANT).status == SubscriptionStatus.CANCELLED


def test_a_failed_payment_marks_past_due_rather_than_active() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body("evt_f", "invoice.payment_failed")
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    assert service.subscription(TENANT).status == SubscriptionStatus.PAST_DUE


def test_an_unknown_event_type_grants_nothing() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body("evt_u", "customer.discount.created")
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    assert service.subscription(TENANT).status == SubscriptionStatus.INACTIVE
    assert service.subscription(TENANT).plan == "free"


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"type": "checkout.session.completed"}).encode(),  # no id
        json.dumps({"id": "evt_x"}).encode(),  # no type
        json.dumps({"id": "evt_x", "type": "t"}).encode(),  # no tenant
        b"not json",
    ],
)
def test_malformed_event_bodies_are_rejected(body: bytes) -> None:
    with pytest.raises(BillingError):
        parse_stripe_event(body, signature(body), SECRET)


def test_an_unknown_plan_is_rejected() -> None:
    body = event_body(plan="platinum")
    with pytest.raises(BillingError, match="unknown plan"):
        parse_stripe_event(body, signature(body), SECRET)


# ------------------------------------------------------------ checkout


def test_checkout_refuses_when_stripe_is_not_configured() -> None:
    """A fabricated checkout URL would be a false promise."""
    service = BillingService(stripe_secret=None)
    with pytest.raises(BillingError, match="not configured"):
        service.create_checkout_session(
            TENANT, "solo", "https://x.test/ok", "https://x.test/cancel"
        )


def test_checkout_refuses_non_https_redirects() -> None:
    service = BillingService(stripe_secret=SECRET)
    with pytest.raises(BillingError, match="https"):
        service.create_checkout_session(
            TENANT, "solo", "http://x.test/ok", "https://x.test/cancel"
        )


def test_portal_refuses_when_stripe_is_not_configured() -> None:
    with pytest.raises(BillingError, match="not configured"):
        BillingService().create_portal_session(TENANT, "https://x.test")


def test_unknown_plan_is_refused_by_the_catalogue() -> None:
    service = BillingService(stripe_secret=SECRET)
    with pytest.raises(BillingError, match="unknown plan"):
        service.create_checkout_session(
            TENANT, "platinum", "https://x.test/ok", "https://x.test/cancel"
        )


# ------------------------------------------------------ manual payment


def test_manual_payment_records_as_pending_and_never_self_activates() -> None:
    service = BillingService()
    result = service.record_manual_payment(TENANT, "clinic", "BACS-0001", ADMIN)

    assert result["status"] == "pending_approval"
    subscription = service.subscription(TENANT)
    assert subscription.status == SubscriptionStatus.PENDING
    assert subscription.method == PaymentMethod.MANUAL
    assert subscription.manual_reference == "BACS-0001"


def test_manual_payment_activates_only_after_an_admin_approval() -> None:
    service = BillingService()
    service.record_manual_payment(TENANT, "solo", "BACS-0002", ADMIN)
    assert service.subscription(TENANT).status == SubscriptionStatus.PENDING

    result = service.approve_manual_payment(TENANT, ADMIN)

    assert result["status"] == "active"
    subscription = service.subscription(TENANT)
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.manual_approved_by == ADMIN
    assert subscription.plan == "solo"


def test_manual_payment_approval_is_audited() -> None:
    service = BillingService()
    service.record_manual_payment(TENANT, "solo", "BACS-0003", ADMIN)
    service.approve_manual_payment(TENANT, ADMIN)

    actions = [event["action"] for event in service.list_audit(TENANT)]
    assert "payment.recorded" in actions
    assert "payment.approved" in actions
    assert actions.index("payment.recorded") < actions.index("payment.approved")
    for event in service.list_audit(TENANT):
        assert event["actor_id"] == str(ADMIN)
        assert event["tenant_id"] == str(TENANT)


def test_a_duplicate_payment_reference_is_refused() -> None:
    service = BillingService()
    service.record_manual_payment(TENANT, "solo", "BACS-0004", ADMIN)
    with pytest.raises(BillingError, match="already recorded"):
        service.record_manual_payment(TENANT, "clinic", "BACS-0004", ADMIN)


@pytest.mark.parametrize("reference", ["", "  ", "ab"])
def test_a_payment_reference_is_required(reference: str) -> None:
    with pytest.raises(BillingError, match="reference"):
        BillingService().record_manual_payment(TENANT, "solo", reference, ADMIN)


def test_the_free_plan_needs_no_payment() -> None:
    with pytest.raises(BillingError, match="free plan"):
        BillingService().record_manual_payment(TENANT, "free", "BACS-0005", ADMIN)


def test_approving_without_a_recorded_payment_is_refused() -> None:
    with pytest.raises(BillingError, match="no manual payment"):
        BillingService().approve_manual_payment(TENANT, ADMIN)


def test_approving_twice_is_refused() -> None:
    service = BillingService()
    service.record_manual_payment(TENANT, "solo", "BACS-0006", ADMIN)
    service.approve_manual_payment(TENANT, ADMIN)
    with pytest.raises(BillingError):
        service.approve_manual_payment(TENANT, ADMIN)


def test_rejecting_returns_the_tenant_to_free_and_keeps_a_reason() -> None:
    service = BillingService()
    service.record_manual_payment(TENANT, "clinic", "BACS-0007", ADMIN)

    result = service.reject_manual_payment(TENANT, ADMIN, "amount did not match")

    assert result["status"] == "rejected"
    assert service.subscription(TENANT).plan == "free"
    rejection = [
        event for event in service.list_audit(TENANT) if event["action"] == "payment.rejected"
    ]
    assert rejection and rejection[0]["reason"] == "amount did not match"


def test_rejection_requires_a_reason() -> None:
    service = BillingService()
    service.record_manual_payment(TENANT, "solo", "BACS-0008", ADMIN)
    with pytest.raises(BillingError, match="reason"):
        service.reject_manual_payment(TENANT, ADMIN, "   ")


# ------------------------------------------------------- caps and limits


def test_caps_refuse_an_inactive_tenant() -> None:
    result = BillingService().enforce_caps(TENANT, 0)
    assert result["allowed"] is False
    assert result["reason"] == "no active subscription"


def test_caps_refuse_past_the_source_limit() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body()
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    assert service.enforce_caps(TENANT, 1)["allowed"] is True
    over = service.enforce_caps(TENANT, PLANS["clinic"]["max_sources"] + 1)
    assert over["allowed"] is False
    assert over["reason"] == "source cap exceeded"


def test_caps_are_tenant_scoped() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body()
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    assert service.enforce_caps(OTHER_TENANT, 0)["allowed"] is False


def test_a_zero_cost_cap_blocks_ai_usage() -> None:
    status = BillingService().cost_cap_status(TENANT, 0.0)
    assert status["capped"] is True
    assert status["action"] == "block_ai_usage"


def test_usage_under_the_cap_is_allowed() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body()
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    status = service.cost_cap_status(TENANT, 1.0)
    assert status["capped"] is False
    assert status["action"] == "allow"


def test_reaching_the_cap_blocks_further_ai_usage() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body()
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    status = service.cost_cap_status(TENANT, PLANS["clinic"]["monthly_cost_cap_usd"])
    assert status["capped"] is True
    assert status["action"] == "block_ai_usage"


# ---------------------------------------------------------- degradation


def test_degradation_keeps_learning_readable_when_billing_is_down() -> None:
    service = BillingService(stripe_secret=None)
    degradation = service.degradation()

    assert degradation["configured"] is False
    assert degradation["read_only_when_unpaid"] is True
    assert degradation["manual_available"] is True
    assert "read-only" in degradation["message"]


def test_no_secret_ever_appears_in_a_public_payload() -> None:
    service = BillingService(stripe_secret=SECRET)
    body = event_body()
    service.handle_event(parse_stripe_event(body, signature(body), SECRET))

    rendered = json.dumps(
        {
            "subscription": service.subscription(TENANT).to_dict(),
            "degradation": service.degradation(),
            "audit": service.list_audit(TENANT),
        }
    )
    assert SECRET not in rendered
    assert "whsec" not in rendered
