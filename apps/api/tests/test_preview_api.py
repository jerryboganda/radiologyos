from __future__ import annotations

from apps.api.app.main import app, settings
from apps.api.app.preview.service import reset_preview_state
from fastapi.testclient import TestClient

client = TestClient(app)
HEADERS = {
    "x-user-id": "10000000-0000-0000-0000-000000000001",
    "x-tenant-id": "20000000-0000-0000-0000-000000000002",
}
OTHER_HEADERS = {
    "x-user-id": "10000000-0000-0000-0000-000000000009",
    "x-tenant-id": "30000000-0000-0000-0000-000000000003",
}


def setup_function() -> None:
    reset_preview_state()
    settings.preview_enabled = True


def teardown_function() -> None:
    settings.preview_enabled = False
    reset_preview_state()


def test_preview_source_page_search_and_delete() -> None:
    created = client.post(
        "/v1/preview/sources",
        headers={**HEADERS, "Idempotency-Key": "api-key"},
        json={
            "title": "Synthetic notes",
            "kind": "note",
            "content": "# Chest\n\nSynthetic finding.",
        },
    )

    assert created.status_code == 202
    source, job = created.json()
    assert source["status"] == "ready"
    assert job["status"] == "succeeded"

    listed = client.get("/v1/preview/sources", headers=HEADERS)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    page = client.get(f"/v1/preview/sources/{source['id']}/pages/1", headers=HEADERS)
    assert page.status_code == 200
    assert page.json()["blocks"][0]["text"] == "Chest"

    search = client.post(
        "/v1/preview/search",
        headers=HEADERS,
        json={"query": "synthetic finding"},
    )
    assert search.status_code == 200
    assert search.json()["chunks"][0]["citation"]["source_id"] == source["id"]

    deleted = client.delete(f"/v1/preview/sources/{source['id']}", headers=HEADERS)
    assert deleted.status_code == 202
    assert client.get(f"/v1/preview/sources/{source['id']}", headers=HEADERS).status_code == 404


def test_preview_routes_reject_cross_tenant_access_and_client_tenant_ids() -> None:
    created = client.post(
        "/v1/preview/sources",
        headers={**HEADERS, "Idempotency-Key": "isolation-key"},
        json={"title": "Tenant A", "kind": "note", "content": "Private synthetic finding."},
    )
    source_id = created.json()[0]["id"]

    assert client.get(f"/v1/preview/sources/{source_id}", headers=OTHER_HEADERS).status_code == 404
    assert (
        client.delete(f"/v1/preview/sources/{source_id}", headers=OTHER_HEADERS).status_code == 404
    )
    same_tenant_other_user = {**HEADERS, "x-user-id": "10000000-0000-0000-0000-000000000009"}
    assert (
        client.get(f"/v1/preview/sources/{source_id}", headers=same_tenant_other_user).status_code
        == 404
    )
    injected = client.post(
        "/v1/preview/sources",
        headers={**HEADERS, "Idempotency-Key": "injected"},
        json={
            "title": "Bad",
            "kind": "note",
            "content": "Text",
            "tenant_id": OTHER_HEADERS["x-tenant-id"],
        },
    )
    assert injected.status_code == 422


def test_preview_routes_are_hidden_when_disabled() -> None:
    settings.preview_enabled = False

    response = client.get("/v1/preview/sources", headers=HEADERS)

    assert response.status_code == 404
