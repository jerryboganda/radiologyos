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

from packages.models.claude_stream import (
    DeltaCallback,
    StreamOutputInvalid,
    json_object_in,
    run_streaming,
    text_json_call,
)

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
    backend: str = "claude_code"
    api_key_env: str | None = None
    base_url: str | None = None

    def __post_init__(self) -> None:
        if self.effort not in EFFORTS:
            raise ValueError(f"unknown effort level: {self.effort}")


@dataclass(slots=True)
class ModelResult:
    output: dict[str, Any]
    duration_ms: int
    cost_usd: float
    usage: dict[str, Any] = field(default_factory=dict)
    backend: str = "claude_code"


@dataclass(slots=True)
class ClaudeCodeTransport:
    binary: str = "claude"
    backends: tuple[str, ...] = ("claude_code",)

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def run(self, call: ModelCall) -> ModelResult:
        binary = self._binary()
        with tempfile.TemporaryDirectory(prefix="radbrain-model-") as work:
            argv = self._argv(binary, call, _stage_files(work, call))
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

    def run_stream(self, call: ModelCall, on_delta: DeltaCallback) -> ModelResult:
        """Like ``run``, but hand every output delta to ``on_delta`` as it arrives.

        Structured output (``--json-schema``) is only delivered in the final
        result, never as deltas, so a streamed call asks for the JSON object as
        plain text instead (see ``claude_stream``). Raises ``StreamUnsupported``
        when the CLI cannot stream and ``StreamOutputInvalid`` when the text is
        not one JSON object; neither is a ModelCallError, so the gateway falls
        back to ``run``, which enforces the schema.
        """
        binary = self._binary()
        with tempfile.TemporaryDirectory(prefix="radbrain-model-") as work:
            argv = self._argv(binary, text_json_call(call), _stage_files(work, call))
            try:
                payload, code, elapsed = run_streaming(argv, work, _child_env(),
                                                       call.timeout_s, on_delta)
            except TimeoutError as exc:
                raise ModelCallError("model call timed out") from exc
        if not payload:
            raise ModelCallError(f"model stream ended without a result (exit {code})")
        return _parse_payload(payload, elapsed, text_json=True)

    def _binary(self) -> str:
        binary = shutil.which(self.binary)
        if binary is None:
            raise ModelCallError("claude CLI is not installed")
        return binary

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


def _stage_files(work: str, call: ModelCall) -> str:
    """Write attached files into the call's empty work dir; return the full prompt."""
    prompt = call.user_prompt
    if call.files:
        paths = []
        for name, data in call.files:
            target = Path(work) / Path(name).name
            target.write_bytes(data)
            paths.append(str(target))
        prompt += "\n\nFiles to read with the Read tool:\n" + "\n".join(paths)
    return prompt


def _parse(stdout: bytes, returncode: int, elapsed_ms: int) -> ModelResult:
    try:
        payload = json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ModelCallError(f"model call returned no JSON (exit {returncode})") from exc
    if not isinstance(payload, dict):
        raise ModelCallError("model call returned an unexpected payload")
    return _parse_payload(payload, elapsed_ms)


def _parse_payload(
    payload: dict[str, Any], elapsed_ms: int, text_json: bool = False
) -> ModelResult:
    if payload.get("is_error") or payload.get("subtype") != "success":
        status = payload.get("api_error_status")
        text = str(payload.get("result") or "").lower()
        if status == 429 or "usage limit" in text or "rate limit" in text:
            raise UsageLimitError("subscription usage limit reached")
        raise ModelCallError(f"model call failed ({payload.get('subtype')}, status {status})")
    output = payload.get("structured_output")
    if text_json and not isinstance(output, dict):
        output = json_object_in(payload.get("result"))
        if output is None:
            raise StreamOutputInvalid("streamed answer was not one JSON object")
    if not isinstance(output, dict):
        raise ModelCallError("model call returned no structured output")
    return ModelResult(
        output=output,
        duration_ms=int(payload.get("duration_ms") or elapsed_ms),
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
        usage=payload.get("usage") or {},
    )
