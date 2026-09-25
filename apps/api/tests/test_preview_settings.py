from __future__ import annotations

import pytest
from apps.api.app.core.config import Settings
from pydantic import ValidationError


def test_preview_mode_is_disabled_by_default() -> None:
    assert Settings().preview_enabled is False


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_preview_outside_local_requires_an_identity_provider(app_env: str) -> None:
    """ADR 0009: preview may ship to production, but only behind authentication.

    Without a JWKS URL there is no identity provider, so the surface would be
    either unreachable or unauthenticated. Refuse to start instead.
    """
    with pytest.raises(ValidationError, match="OIDC_JWKS_URL"):
        Settings(app_env=app_env, preview_enabled=True)


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_preview_is_permitted_with_a_configured_issuer(app_env: str) -> None:
    settings = Settings(
        app_env=app_env,
        preview_enabled=True,
        oidc_issuer="https://auth.example.test/realms/radbrain",
        oidc_jwks_url="https://auth.example.test/realms/radbrain/protocol/openid-connect/certs",
    )

    assert settings.preview_enabled is True
    assert settings.is_local_development is False


def test_preview_mode_can_be_enabled_for_tests_without_an_issuer() -> None:
    settings = Settings(app_env="test", preview_enabled=True)

    assert settings.preview_enabled is True
    assert settings.is_local_development is True
