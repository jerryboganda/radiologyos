"""Claude Code headless transport for the named model routes (ADR 0010).

Each call runs ``claude -p`` in an empty temporary directory with a fixed
system prompt, an explicit tool allow-list, a JSON Schema for the output, and
no session persistence. Authentication is the owner's subscription token in
``CLAUDE_CODE_OAUTH_TOKEN``; it is inherited from the environment and never
logged. Prompts and outputs are never logged either (hard rule 4): callers log
only ids, hashes, durations, and outcomes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - fixed argv, no shell
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EFFORTS = ("low", "medium", "high", "xhigh", "max")


class ModelCallError(RuntimeError):
    """A model call failed; the message never contains prompt or output text."""


class UsageLimitError(ModelCallError):
    """The subscription usage window is exhausted; retry later."""


@dataclass(frozen=True, slots=True)
class ModelCall:
    model: str
    effort: str
    system_prompt: str
    user_prompt: str
    output_schema: dict[str, Any]
    files: Sequence[tuple[str, bytes]] = ()
    tools: Sequence[str] = ()
    timeout_s: int = 600

    def __post_init__(self) -> None:
        if self.effort not in EFFORTS:
            raise ValueError(f"unknown effort level: {self.effort}")


@dataclass(slots=True)
class ModelResult:
    output: dict[str, Any]
    duration_ms: int
    cost_usd: float
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ClaudeCodeTransport:
    binary: str = "claude"

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def run(self, call: ModelCall) -> ModelResult:
        binary = shutil.which(self.binary)
        if binary is None:
            raise ModelCallError("claude CLI is not installed")
        with tempfile.TemporaryDirectory(prefix="radbrain-model-") as work:
            prompt = call.user_prompt
            if call.files:
                paths = []
                for name, data in call.files:
                    safe = Path(name).name
                    target = Path(work) / safe
                    target.write_bytes(data)
                    paths.append(str(target))
                prompt += "\n\nFiles to read with the Read tool:\n" + "\n".join(paths)
            argv = self._argv(binary, call, prompt)
            started = time.monotonic()
            completed = subprocess.run(  # nosec B603 - fixed argv, no shell
                argv,
                cwd=work,
                capture_output=True,
                timeout=call.timeout_s,
                check=False,
                env=_child_env(),
            )
        elapsed = int((time.monotonic() - started) * 1000)
        return _parse(completed.stdout, completed.returncode, elapsed)

    @staticmethod
    def _argv(binary: str, call: ModelCall, prompt: str) -> list[str]:
        tools = list(call.tools)
        if call.files and "Read" not in tools:
            tools.append("Read")
        argv = [
            binary,
            "-p",
            prompt,
            "--model",
            call.model,
            "--effort",
            call.effort,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(call.output_schema, separators=(",", ":")),
            "--system-prompt",
            call.system_prompt,
            "--tools",
            ",".join(tools),
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        if tools:
            argv += ["--allowedTools", ",".join(tools)]
        return argv


def _child_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "TEMP",
            "TMP", "LANG", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    return env


def _parse(stdout: bytes, returncode: int, elapsed_ms: int) -> ModelResult:
    try:
        payload = json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ModelCallError(f"model call returned no JSON (exit {returncode})") from exc
    if not isinstance(payload, dict):
        raise ModelCallError("model call returned an unexpected payload")
    if payload.get("is_error") or payload.get("subtype") != "success":
        status = payload.get("api_error_status")
        text = str(payload.get("result") or "").lower()
        if status == 429 or "usage limit" in text or "rate limit" in text:
            raise UsageLimitError("subscription usage limit reached")
        raise ModelCallError(f"model call failed ({payload.get('subtype')}, status {status})")
    output = payload.get("structured_output")
    if not isinstance(output, dict):
        raise ModelCallError("model call returned no structured output")
    return ModelResult(
        output=output,
        duration_ms=int(payload.get("duration_ms") or elapsed_ms),
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
        usage=payload.get("usage") or {},
    )
