from __future__ import annotations

import pytest
from apps.api.app.core.config import Settings
from pydantic import ValidationError


def test_preview_mode_is_disabled_by_default() -> None:
    assert Settings().preview_enabled is False


def test_preview_mode_requires_a_local_environment() -> None:
    with pytest.raises(ValidationError, match="preview mode"):
        Settings(app_env="staging", preview_enabled=True)


def test_preview_mode_can_be_enabled_for_tests() -> None:
    settings = Settings(app_env="test", preview_enabled=True)

    assert settings.preview_enabled is True
