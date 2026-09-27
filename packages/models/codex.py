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
import queue
import re
import shutil
import subprocess  # nosec B404 - fixed argv to the codex CLI, no shell
import tempfile
import threading
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
            try:
                return _result(done, Path(work) / "last.json", elapsed)
            except UsageLimitError:
                raise
            except ModelCallError:
                # An unexplained failure may still be the quota with an unfamiliar
                # message: ask the account, so a spent quota pauses the run instead
                # of marking good pages failed (owner: never lose progress).
                reached, retry = limit_reached(rate_limits(binary))
                if reached:
                    raise UsageLimitError("codex usage limit reached", retry, "chatgpt") from None
                raise


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


_UNITS = {"day": 86400, "hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1,
          "sec": 1}
_AFTER = re.compile(r"try again in ((?:\s*(?:and\s+)?\d+\s*(?:days?|hours?|hrs?|minutes?|mins?"
                    r"|seconds?|secs?)\b,?)+)")
_PART = re.compile(r"(\d+)\s*(day|hour|hr|minute|min|second|sec)")


def retry_after(text: str) -> int | None:
    """Seconds until the quota resets, from "try again in 2 hours 5 minutes"; else None."""
    found = _AFTER.search(text.lower())
    if found is None:
        return None
    seconds = sum(int(n) * _UNITS[unit] for n, unit in _PART.findall(found.group(1)))
    return seconds or None


def _result(done: subprocess.CompletedProcess[bytes], last: Path, elapsed: int) -> ModelResult:
    if done.returncode != 0 or not last.exists():
        text = (done.stderr + done.stdout).decode("utf-8", "replace").lower()
        if any(marker in text for marker in LIMIT_MARKERS):
            raise UsageLimitError("codex usage limit reached", retry_after(text), "chatgpt")
        raise ModelCallError(f"codex exited with status {done.returncode}")
    try:
        output = json.loads(last.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelCallError("codex answer was not JSON") from exc
    if not isinstance(output, dict):
        raise ModelCallError("codex answer was not a JSON object")
    return ModelResult(output=output, duration_ms=elapsed, cost_usd=0.0, backend="codex")


_PROBE = (
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"clientInfo": {"name": "radbrain", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"},
)


def rate_limits(binary: str, timeout_s: float = 25.0) -> dict[str, Any] | None:
    """The account's current ChatGPT limits from ``codex app-server`` (no model call)."""
    with tempfile.TemporaryDirectory(prefix="radbrain-codex-") as work:
        try:
            proc = subprocess.Popen(  # nosec B603 - fixed argv, no shell
                [binary, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=work)
        except OSError:
            return None
        lines: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=_pump, args=(proc, lines), daemon=True).start()
        try:
            assert proc.stdin is not None
            proc.stdin.write(b"".join(json.dumps(m).encode() + b"\n" for m in _PROBE))
            proc.stdin.flush()
            deadline = time.monotonic() + timeout_s
            while (left := deadline - time.monotonic()) > 0:
                try:
                    reply = json.loads(lines.get(timeout=left))
                except (queue.Empty, ValueError):
                    continue
                if isinstance(reply, dict) and reply.get("id") == 2:
                    result = reply.get("result")
                    return result if isinstance(result, dict) else None
            return None
        except OSError:
            return None
        finally:
            proc.kill()
            proc.wait(timeout=5)


def _pump(proc: subprocess.Popen[bytes], lines: queue.Queue[bytes]) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.put(line)


def limit_reached(
    limits: dict[str, Any] | None, now: float | None = None
) -> tuple[bool, int | None]:
    """(spent, seconds until the spent window resets) from ``rate_limits``."""
    if not limits:
        return False, None
    info = limits.get("rateLimits") or {}
    windows = [w for w in (info.get("primary"), info.get("secondary")) if isinstance(w, dict)]
    full = [w for w in windows if (w.get("usedPercent") or 0) >= 100]
    spent = bool(full or info.get("rateLimitReachedType")
                 or limits.get("ordinaryUsageAllowed") is False)
    if not spent:
        return False, None
    resets = [int(w["resetsAt"]) for w in full if w.get("resetsAt")]
    retry = max(resets) - int(now or time.time()) if resets else None
    return True, retry if retry and retry > 0 else None
