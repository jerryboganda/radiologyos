"""Stripe-style webhook signature verification and event parsing."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from apps.api.app.billing.models import (
    EVENT_STATUS,
    PLANS,
    BillingError,
    BillingEvent,
    SignatureError,
    SubscriptionStatus,
)


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

def status_for_event(event: BillingEvent) -> SubscriptionStatus:
    mapping = EVENT_STATUS
    payload_status = event.payload.get("status")
    if payload_status in {"past_due", "unpaid", "canceled"}:
        return SubscriptionStatus.PAST_DUE
    return mapping[event.event_type]

