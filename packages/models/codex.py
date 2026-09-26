"""Codex CLI transport: ChatGPT models on the owner's subscription (ADR 0035).

Runs ``codex exec`` headless with the target model and reasoning effort, the
agent's JSON Schema as ``--output-schema``, attached images as ``-i``, and a
read-only sandbox with no approvals, in an empty temporary work dir. The sign-in
(OAuth, from ``codex login --device-auth``) lives in ``CODEX_HOME`` on the host,
never in the repository. Prompts and outputs are never logged (hard rule 4).

Codex has no separate system prompt flag, so the agent's system prompt leads
the prompt under a fixed heading; the schema still constrains the answer and
the gateway validates it afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - fixed argv to the codex CLI, no shell
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
LIMIT_MARKERS = ("usage limit", "rate limit", "quota", "too many requests", "429")


@dataclass(slots=True)
class CodexTransport:
    binary: str = "codex"
    backends: tuple[str, ...] = ("codex",)

    def available(self) -> bool:
        """The CLI is installed and a ChatGPT sign-in is stored in CODEX_HOME."""
        if shutil.which(self.binary) is None:
            return False
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        return (home / "auth.json").exists()

    def run(self, call: ModelCall) -> ModelResult:
        binary = shutil.which(self.binary)
        if binary is None:
            raise ModelCallError("codex CLI is not installed")
        with tempfile.TemporaryDirectory(prefix="radbrain-codex-") as work:
            argv, prompt = _argv(binary, call, Path(work))
            started = time.monotonic()
            try:
                done = subprocess.run(  # nosec B603 - fixed argv, no shell
                    argv, input=prompt.encode("utf-8"), capture_output=True,
                    timeout=call.timeout_s, cwd=work, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ModelCallError(f"codex timed out after {call.timeout_s}s") from exc
            elapsed = int((time.monotonic() - started) * 1000)
            return _result(done, Path(work) / "last.json", elapsed)


def _argv(binary: str, call: ModelCall, work: Path) -> tuple[list[str], str]:
    schema = work / "schema.json"
    schema.write_text(json.dumps(_strict(call.output_schema)), encoding="utf-8")
    argv = [binary, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
            "-c", 'approval_policy="never"', "-m", call.model,
            "-c", f'model_reasoning_effort="{call.effort}"',
            "--output-schema", str(schema), "-o", str(work / "last.json"), "--color", "never"]
    if call.speed == "fast":
        argv += ["-c", 'service_tier="priority"']  # the catalog's "Fast" tier
    for name, data in call.files:
        path = work / Path(name).name
        path.write_bytes(data)
        if path.suffix.lower() in IMAGE_SUFFIXES:
            argv += ["-i", str(path)]
    argv.append("-")  # the prompt arrives on stdin, never on the command line
    prompt = (f"# Instructions\n\n{call.system_prompt}\n\n# Task\n\n{call.user_prompt}\n\n"
              "Answer with the JSON object only. Do not run commands or read files.")
    return argv, prompt


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI structured outputs need additionalProperties false on every object."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            out[key] = _strict(value)
        elif isinstance(value, list):
            out[key] = [_strict(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    if out.get("type") == "object" and "additionalProperties" not in out:
        out["additionalProperties"] = False
    return out


def _result(done: subprocess.CompletedProcess[bytes], last: Path, elapsed: int) -> ModelResult:
    if done.returncode != 0 or not last.exists():
        text = (done.stderr + done.stdout).decode("utf-8", "replace").lower()
        if any(marker in text for marker in LIMIT_MARKERS):
            raise UsageLimitError("codex usage limit reached")
        raise ModelCallError(f"codex exited with status {done.returncode}")
    try:
        output = json.loads(last.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelCallError("codex answer was not JSON") from exc
    if not isinstance(output, dict):
        raise ModelCallError("codex answer was not a JSON object")
    return ModelResult(output=output, duration_ms=elapsed, cost_usd=0.0, backend="codex")
