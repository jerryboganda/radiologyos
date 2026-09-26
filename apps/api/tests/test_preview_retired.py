"""ADR 0031: the in-memory preview surface is gone, and its old switch is inert."""

from __future__ import annotations

import pytest
from apps.api.app.core.config import Settings
from apps.api.app.main import app
from fastapi.testclient import TestClient

HEADERS = {
    "x-user-id": "10000000-0000-0000-0000-000000000001",
    "x-tenant-id": "20000000-0000-0000-0000-000000000002",
    "x-role": "superadmin",
}


def test_no_preview_route_is_mounted() -> None:
    assert not [path for path in app.openapi()["paths"] if "preview" in path]


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/v1/preview/sources"), ("POST", "/v1/preview/search"),
     ("GET", "/v1/preview/export/markdown"), ("GET", "/v1/preview/capabilities")],
)
def test_former_preview_paths_answer_404_even_to_a_superadmin(method: str, path: str) -> None:
    response = TestClient(app).request(method, path, headers=HEADERS, json={})
    assert response.status_code == 404


@pytest.mark.parametrize("value", ["true", "false"])
def test_a_leftover_preview_env_var_is_tolerated(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PREVIEW_ENABLED", value)
    settings = Settings(app_env="production")
    assert not hasattr(settings, "preview_enabled")
