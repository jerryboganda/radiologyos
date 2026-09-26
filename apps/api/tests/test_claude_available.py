"""The Claude transport is available only with the CLI and a credential (503, not 502)."""

from __future__ import annotations

from pathlib import Path

import pytest
from packages.models import claude_code
from packages.models.claude_code import ClaudeCodeTransport


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(claude_code.shutil, "which", lambda _b: "/usr/bin/claude")
    monkeypatch.setattr(claude_code.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def test_no_credential_means_unavailable(cli: Path) -> None:
    assert not ClaudeCodeTransport().available()


def test_a_token_or_a_local_login_makes_it_available(
    cli: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    assert ClaudeCodeTransport().available()
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    (cli / ".claude").mkdir()
    (cli / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
    assert ClaudeCodeTransport().available()


def test_no_cli_means_unavailable_even_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_code.shutil, "which", lambda _b: None)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")
    assert not ClaudeCodeTransport().available()


def test_a_blank_tutor_question_is_rejected_before_any_model_call() -> None:
    from apps.api.app.tutor.contracts import AskRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AskRequest(question="   \n\t  ")
    assert AskRequest(question="  crazy paving  ").question == "crazy paving"
