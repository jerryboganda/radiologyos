"""Web Push delivery (VAPID) and reminder message composition.

The payload carries only counts and a link, never study content, so a push
service in the middle learns nothing about the user's material. Subscriptions
that the push service reports as gone (404/410) are removed by the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

VAPID_SUBJECT = "https://radiologyos.polytronx.com"


class PushGone(Exception):
    """The subscription no longer exists; delete it."""


class PushFailed(Exception):
    """Delivery failed for another reason; count it and retry next time."""


@dataclass(frozen=True, slots=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


def reminder_payload(
    due_cards: int | None, days_to_exam: int | None, plan_minutes: int | None
) -> dict[str, Any]:
    parts = []
    if days_to_exam is not None:
        parts.append(f"{days_to_exam} days to your exam")
    if due_cards:
        parts.append(f"{due_cards} card{'s' if due_cards != 1 else ''} due")
    if plan_minutes:
        parts.append(f"today's plan: {plan_minutes} min")
    body = " · ".join(parts) or "Your study session is ready."
    return {"title": "radbrain — time to study", "body": body, "url": "/today", "tag": "daily"}


def send(subscription: Subscription, payload: dict[str, Any], private_key: str) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=6 * 3600,
            timeout=15,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone from exc
        raise PushFailed(f"push failed with status {status}") from exc


def generate_vapid_keys() -> tuple[str, str]:
    """Return (private_key_pem_b64url, public_key_b64url) for app.env."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    vapid = Vapid02()
    vapid.generate_keys()
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    public = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    private_number = vapid.private_key.private_numbers().private_value
    private = base64.urlsafe_b64encode(private_number.to_bytes(32, "big")).rstrip(b"=").decode()
    return private, public
