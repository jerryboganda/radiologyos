"""Dispatch model calls to the backend each target names (ADR 0027)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from packages.models.claude_code import ClaudeCodeTransport, ModelCall, ModelCallError, ModelResult
from packages.models.codex import CodexTransport
from packages.models.mistral import MistralTransport


@dataclass(slots=True)
class MultiTransport:
    """Routes each call by ``call.backend``; ``backends`` lists what it can serve."""

    transports: dict[str, Any]

    @property
    def backends(self) -> tuple[str, ...]:
        return tuple(self.transports)

    def run(self, call: ModelCall) -> ModelResult:
        transport = self.transports.get(call.backend)
        if transport is None:
            raise ModelCallError(f"no transport for backend {call.backend}")
        result: ModelResult = transport.run(call)
        return result


def default_transport(claude_binary: str) -> MultiTransport | None:
    """Every backend that has credentials here; None when none does.

    The Claude CLI path comes from application Settings (``CLAUDE_CODE_BIN``),
    never read here, so one setting governs every process (ADR 0032).
    """
    transports: dict[str, Any] = {}
    claude = ClaudeCodeTransport(claude_binary)
    has_token = bool(
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    )
    if claude.available() and has_token:
        transports["claude_code"] = claude
    mistral = MistralTransport()
    if mistral.available():
        transports["mistral"] = mistral
    codex = CodexTransport(os.environ.get("CODEX_BIN", "codex"))
    if codex.available():  # ChatGPT subscription sign-in present (ADR 0035)
        transports["codex"] = codex
    return MultiTransport(transports) if transports else None
