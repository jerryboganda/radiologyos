"""Shared fixtures for the M6 billing eval gates (not a test module)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from apps.api.app.api.billing import reset_billing_service
from apps.api.app.main import app, settings
from fastapi.testclient import TestClient

client = TestClient(app)
TENANT = UUID("40000000-0000-0000-0000-000000000001")
OTHER_TENANT = UUID("40000000-0000-0000-0000-0000000000ff")
ADMIN = UUID("10000000-0000-0000-0000-00000000000a")
SECRET = "whsec_test_do_not_use_in_production"
HEADERS = {
    "x-user-id": "10000000-0000-0000-0000-00000000000a",
    "x-tenant-id": "40000000-0000-0000-0000-000000000001",
    "x-role": "org_admin",
}


def enable_billing() -> None:
    settings.app_env = "test"
    settings.billing_enabled = True
    reset_billing_service()


def restore_settings() -> None:
    settings.app_env = "dev"
    settings.billing_enabled = False
    reset_billing_service()


def signature(payload: bytes, secret: str = SECRET, stamp: int | None = None) -> str:
    ts = stamp if stamp is not None else int(datetime.now(UTC).timestamp())
    signed = f"{ts}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def event_body(
    event_id: str = "evt_1",
    event_type: str = "checkout.session.completed",
    plan: str = "clinic",
    tenant: str = str(TENANT),
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "data": {
                "object": {
                    "status": "complete",
                    "metadata": {"tenant_id": tenant, "plan": plan},
                }
            },
        }
    ).encode()
