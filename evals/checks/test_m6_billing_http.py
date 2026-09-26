"""M6 eval gate: the billing HTTP surface, and that it stays parked (ADR 0011)."""

from __future__ import annotations

from apps.api.app.billing.service import PLANS
from evals.checks._billing_support import (
    HEADERS,
    client,
    enable_billing,
    event_body,
    restore_settings,
    settings,
    signature,
)


def setup_function() -> None:
    enable_billing()


def teardown_function() -> None:
    restore_settings()


def test_billing_is_absent_unless_enabled() -> None:
    settings.billing_enabled = False
    for path in ("/v1/billing/plans", "/v1/billing/subscription", "/v1/billing/audit"):
        assert client.get(path, headers=HEADERS).status_code == 404


# ------------------------------------------------------------ over HTTP


def test_billing_routes_require_authentication() -> None:
    for path in ("/v1/billing/subscription", "/v1/billing/plans", "/v1/billing/audit"):
        assert client.get(path).status_code in {401, 403}


def test_billing_subscription_and_plans_over_http() -> None:
    plans = client.get("/v1/billing/plans", headers=HEADERS)
    assert plans.status_code == 200
    assert {plan["plan"] for plan in plans.json()} == set(PLANS)

    subscription = client.get("/v1/billing/subscription", headers=HEADERS)
    assert subscription.status_code == 200
    assert subscription.json()["plan"] == "free"
    assert subscription.json()["status"] == "inactive"


def test_manual_approval_requires_an_admin_role_over_http() -> None:
    student = {**HEADERS, "x-role": "student"}
    recorded = client.post(
        "/v1/billing/manual/record",
        headers=student,
        json={"plan": "solo", "reference": "BACS-HTTP-1"},
    )
    assert recorded.status_code == 200
    assert recorded.json()["status"] == "pending_approval"

    denied = client.post("/v1/billing/manual/approve", headers=student)
    assert denied.status_code == 403

    approved = client.post("/v1/billing/manual/approve", headers=HEADERS)
    assert approved.status_code == 200
    assert approved.json()["subscription"]["status"] == "active"


def test_audit_is_privileged_over_http() -> None:
    student = {**HEADERS, "x-role": "student"}
    assert client.get("/v1/billing/audit", headers=student).status_code == 403
    assert client.get("/v1/billing/audit", headers=HEADERS).status_code == 200


def test_webhook_without_a_signature_is_refused() -> None:
    response = client.post("/v1/billing/webhook/stripe", content=event_body())
    assert response.status_code == 400


def test_webhook_is_refused_when_stripe_is_unconfigured() -> None:
    body = event_body()
    response = client.post(
        "/v1/billing/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": signature(body)},
    )
    assert response.status_code == 501


def test_checkout_is_refused_when_stripe_is_unconfigured() -> None:
    response = client.post(
        "/v1/billing/checkout",
        headers=HEADERS,
        json={
            "plan": "solo",
            "success_url": "https://radiologyos.polytronx.com/ok",
            "cancel_url": "https://radiologyos.polytronx.com/cancel",
        },
    )
    assert response.status_code == 402
