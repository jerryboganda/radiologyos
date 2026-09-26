from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.api.notifications import Settings, SubscriptionIn
from packages.notifications.push import generate_vapid_keys, reminder_payload


def test_reminder_payload_carries_counts_only() -> None:
    payload = reminder_payload(3, 120, 90)
    assert payload["url"] == "/today"
    assert "3 cards due" in payload["body"] and "120 days" in payload["body"]
    assert reminder_payload(None, None, None)["body"] == "Your study session is ready."
    assert "1 card due" in reminder_payload(1, None, None)["body"]


def test_settings_reject_unknown_timezone_and_channel() -> None:
    assert Settings(timezone="Asia/Karachi").timezone == "Asia/Karachi"
    with pytest.raises(ValidationError):
        Settings(timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        Settings.model_validate({"channels": ["sms"]})


def test_subscription_requires_https_endpoint() -> None:
    with pytest.raises(ValidationError):
        SubscriptionIn(endpoint="http://push.example/x", p256dh="p" * 20, auth="a" * 10)


def test_vapid_keys_have_expected_lengths() -> None:
    private, public = generate_vapid_keys()
    assert len(private) == 43 and len(public) == 87
