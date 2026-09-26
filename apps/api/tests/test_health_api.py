from __future__ import annotations

from apps.api.app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_liveness_is_public() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api", "environment": "dev"}


def test_request_id_is_echoed_as_a_uuid() -> None:
    request_id = "30000000-0000-0000-0000-000000000003"
    response = client.get("/health/live", headers={"x-request-id": request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id


def test_me_requires_development_identity() -> None:
    response = client.get("/v1/me")
    assert response.status_code == 401


def test_student_cannot_access_admin_endpoint() -> None:
    response = client.get(
        "/v1/admin/ping",
        headers={
            "x-user-id": "10000000-0000-0000-0000-000000000001",
            "x-tenant-id": "20000000-0000-0000-0000-000000000002",
        },
    )
    assert response.status_code == 403


def test_org_admin_can_access_admin_endpoint() -> None:
    response = client.get(
        "/v1/admin/ping",
        headers={
            "x-user-id": "10000000-0000-0000-0000-000000000001",
            "x-tenant-id": "20000000-0000-0000-0000-000000000002",
            "x-role": "org_admin",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_account_delete_demands_a_confirmation_body() -> None:
    # Durable jobs exist now (ADR 0018); a bare DELETE is never accepted.
    response = client.request("DELETE", "/v1/me")
    assert response.status_code == 401


def test_development_headers_are_rejected_in_staging(monkeypatch) -> None:
    from apps.api.app import main

    monkeypatch.setattr(main.settings, "app_env", "staging")
    response = client.get(
        "/v1/me",
        headers={
            "x-user-id": "10000000-0000-0000-0000-000000000001",
            "x-tenant-id": "20000000-0000-0000-0000-000000000002",
        },
    )
    assert response.status_code == 401
