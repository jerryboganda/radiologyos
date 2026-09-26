"""Tests for the Claude Code transport, agent gateway, assertions, and embeddings."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from apps.api.app.security.internal import (
    AUDIENCE,
    ISSUER,
    AssertionError_,
    verify_internal_assertion,
)
from packages.library.parse_models import PageParse, inline_schema
from packages.models.claude_code import (
    ClaudeCodeTransport,
    ModelCall,
    ModelCallError,
    ModelResult,
    UsageLimitError,
    _parse,
)
from packages.models.gateway import build_call, load_agent, routing_config, run_agent

SECRET = "s" * 40


def _call(**overrides: Any) -> ModelCall:
    values: dict[str, Any] = {
        "model": "claude-opus-5-5", "effort": "high", "system_prompt": "sys",
        "user_prompt": "user", "output_schema": {"type": "object"},
    }
    return ModelCall(**{**values, **overrides})


def test_parse_success_returns_structured_output() -> None:
    body = json.dumps({"subtype": "success", "is_error": False, "structured_output": {"a": 1},
                       "duration_ms": 12, "total_cost_usd": 0.5}).encode()
    result = _parse(body, 0, 99)
    assert (result.output, result.duration_ms, result.cost_usd) == ({"a": 1}, 12, 0.5)


def test_parse_maps_usage_limits_and_errors() -> None:
    limited = json.dumps({"subtype": "error", "is_error": True, "api_error_status": 429}).encode()
    with pytest.raises(UsageLimitError):
        _parse(limited, 1, 1)
    with pytest.raises(ModelCallError):
        _parse(b"not json", 1, 1)
    missing = json.dumps({"subtype": "success", "is_error": False}).encode()
    with pytest.raises(ModelCallError, match="no structured output"):
        _parse(missing, 0, 1)


def test_errors_never_echo_prompt_text() -> None:
    payload = {"subtype": "error", "is_error": True, "result": "SECRET PATIENT TEXT"}
    with pytest.raises(ModelCallError) as caught:
        _parse(json.dumps(payload).encode(), 1, 1)
    assert "SECRET" not in str(caught.value)


def test_argv_pins_model_effort_schema_and_tools() -> None:
    argv = ClaudeCodeTransport._argv("claude", _call(files=[("p.png", b"x")]), "prompt")
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--effort") + 1] == "high"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == {"type": "object"}
    assert argv[argv.index("--tools") + 1] == "Read"
    assert "--no-session-persistence" in argv and "--bare" not in argv


def test_unknown_effort_is_rejected() -> None:
    with pytest.raises(ValueError):
        _call(effort="extreme")


def test_page_parse_agent_uses_low_effort_and_generated_schema() -> None:
    agent = load_agent("page_parse")
    assert agent.schema == inline_schema(PageParse)
    call = build_call(agent, "prompt")
    route = routing_config().routes[agent.prompt.route].targets[0]
    assert (call.model, call.effort) == (route.model, "low")
    assert call.tools == ("Read",)


class FakeTransport:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[ModelCall] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        return ModelResult(output=self.output, duration_ms=1, cost_usd=0.0)


def test_run_agent_validates_output() -> None:
    good = {"page_type": "blank", "blocks": [], "figures": [], "topics": []}
    parsed, _ = run_agent(FakeTransport(good), "page_parse", "p")
    assert isinstance(parsed, PageParse)
    with pytest.raises(ModelCallError, match="schema validation"):
        run_agent(FakeTransport({"page_type": "nonsense"}), "page_parse", "p")


def _assertion(**claims: Any) -> str:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": AUDIENCE, "sub": "user-1", "iat": now, "exp": now + 60}
    return jwt.encode({**base, **claims}, SECRET, algorithm="HS256")


def test_internal_assertion_accepts_only_short_lived_signed_subjects() -> None:
    assert verify_internal_assertion(_assertion(), SECRET).subject == "user-1"
    for bad in (
        _assertion(aud="radbrain-api"),
        _assertion(iss="someone-else"),
        _assertion(exp=int(time.time()) + 3600),
        _assertion(exp=int(time.time()) - 60),
    ):
        with pytest.raises(AssertionError_):
            verify_internal_assertion(bad, SECRET)
    with pytest.raises(AssertionError_):
        verify_internal_assertion(_assertion(), "short")
    with pytest.raises(AssertionError_):
        verify_internal_assertion(_assertion(), "x" * 40)
