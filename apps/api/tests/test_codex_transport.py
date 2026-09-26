"""Codex CLI transport and the owner-approval gate (ADR 0035, owner model rules)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from packages.models import codex, gateway
from packages.models.claude_code import (
    ModelCall,
    ModelCallError,
    ModelResult,
    OwnerApprovalRequired,
    UsageLimitError,
)
from packages.models.codex import CodexTransport

SCHEMA = {"type": "object", "properties": {"a": {"type": "object", "properties": {}}},
          "required": ["a"]}


def _call(**extra: Any) -> ModelCall:
    base: dict[str, Any] = {"model": "gpt-test", "effort": "high", "system_prompt": "SYS",
                            "user_prompt": "USER", "output_schema": SCHEMA, "backend": "codex"}
    return ModelCall(**{**base, **extra})


def _fake_run(seen: dict[str, Any], answer: str | None, code: int = 0, err: bytes = b""):
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["argv"], seen["input"] = argv, kwargs["input"].decode()
        schema = Path(argv[argv.index("--output-schema") + 1])
        seen["schema"] = json.loads(schema.read_text(encoding="utf-8"))
        if answer is not None:
            Path(argv[argv.index("-o") + 1]).write_text(answer, encoding="utf-8")
        return subprocess.CompletedProcess(argv, code, b"", err)
    return run


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex.shutil, "which", lambda _b: "/usr/local/bin/codex")


def test_runs_read_only_with_model_effort_speed_schema_and_images(
    cli: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(codex.subprocess, "run", _fake_run(seen, '{"a": {}}'))
    call = _call(speed="fast", files=(("page.png", b"\x89PNG"), ("notes.txt", b"x")))
    result = CodexTransport().run(call)
    argv = seen["argv"]
    assert result.output == {"a": {}} and result.backend == "codex"
    assert argv[:2] == ["/usr/local/bin/codex", "exec"] and argv[-1] == "-"
    assert "read-only" in argv and 'approval_policy="never"' in argv and "--ephemeral" in argv
    assert argv[argv.index("-m") + 1] == "gpt-test"
    assert 'model_reasoning_effort="high"' in argv and 'service_tier="priority"' in argv
    assert [argv[i + 1].endswith("page.png") for i, a in enumerate(argv) if a == "-i"] == [True]
    assert seen["schema"]["additionalProperties"] is False
    assert seen["schema"]["properties"]["a"]["additionalProperties"] is False
    assert "SYS" in seen["input"] and "USER" in seen["input"]  # prompt via stdin only
    assert "USER" not in " ".join(argv)


def test_usage_limits_pause_and_other_failures_fall_through(
    cli: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(codex.subprocess, "run",
                        _fake_run({}, None, 1, b"You've hit your usage limit"))
    with pytest.raises(UsageLimitError):
        CodexTransport().run(_call())
    monkeypatch.setattr(codex.subprocess, "run", _fake_run({}, "not json"))
    with pytest.raises(ModelCallError):
        CodexTransport().run(_call())


def test_available_needs_the_cli_and_a_stored_sign_in(
    cli: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert not CodexTransport().available()
    (tmp_path / "auth.json").write_text("{}", encoding="utf-8")
    assert CodexTransport().available()


class _Chain:
    """Fails every served target, recording which models were actually called."""

    backends = ("codex", "claude_code")

    def __init__(self) -> None:
        self.models: list[str] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.models.append(call.model)
        raise ModelCallError("down")


def test_the_claude_step_waits_for_the_owner_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [_call(model="luna"), _call(model="sol"),
             _call(model="opus", backend="claude_code", requires_approval=True)]
    monkeypatch.setattr(gateway, "build_calls", lambda *_a, **_k: calls)
    monkeypatch.delenv("BULK_CLAUDE_FALLBACK_APPROVED", raising=False)
    chain = _Chain()
    with pytest.raises(OwnerApprovalRequired):
        gateway.run_agent(chain, "page_parse", "p")
    assert chain.models == ["luna", "sol"]  # Opus was never called
    monkeypatch.setenv("BULK_CLAUDE_FALLBACK_APPROVED", "true")
    chain = _Chain()
    with pytest.raises(ModelCallError):
        gateway.run_agent(chain, "page_parse", "p")
    assert chain.models == ["luna", "sol", "opus"]
