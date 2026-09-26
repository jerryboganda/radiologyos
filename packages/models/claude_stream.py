"""Token streaming for the Claude Code headless transport (ADR 0025).

``claude -p --output-format stream-json --verbose --include-partial-messages``
prints one JSON object per line: a ``system`` init line, ``stream_event`` lines
that wrap the Messages API stream events, whole ``assistant``/``user`` messages,
and one final ``result`` line with the same fields as ``--output-format json``.
Every text or partial-JSON delta is handed to ``on_delta(block, chunk)``, where
``block`` numbers content blocks across the whole run, so the caller can follow
the structured output as it is written whether the CLI emits it as text or as a
tool call. The final ``result`` line is parsed like the non-streaming path, so
usage-limit mapping and error hygiene are identical.

Claude Code documents that structured output (``--json-schema``) appears only
in the final result, never as deltas. A streamed call therefore drops
``--json-schema`` and asks for the same JSON object as plain text (the schema
is appended to the system prompt); the gateway validates that object against
the agent's Pydantic model exactly as before. If the CLI prints nothing
parseable (for example an older CLI that rejects the flags before calling any
model) ``StreamUnsupported`` is raised, and if the reply is not one JSON object
``StreamOutputInvalid`` is raised; in both cases the gateway falls back to one
ordinary schema-enforced call. Nothing here logs prompt, delta, or output text
(hard rule 4).
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed argv, no shell
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.models.claude_code import ModelCall

DeltaCallback = Callable[[int, str], None]
STREAM_FLAGS = ("--output-format", "stream-json", "--verbose", "--include-partial-messages")


# Output framing, not an agent prompt: it replaces what ``--json-schema`` does
# for a non-streamed call, because the CLI delivers structured output only in
# the final result and never as deltas. The gateway still validates the object
# against the agent's Pydantic model and falls back to a schema-enforced call.
TEXT_JSON_FRAME = (
    "\n\nOUTPUT FORMAT: reply with exactly one JSON object and nothing else - no prose, "
    "no Markdown, no code fences. It must validate against this JSON Schema:\n{schema}"
)


class StreamUnsupported(RuntimeError):
    """The CLI produced no stream at all; the caller should run a plain JSON call."""


class StreamOutputInvalid(RuntimeError):
    """A streamed answer was not one JSON object; the caller should run a plain JSON call."""


def text_json_call(call: ModelCall) -> ModelCall:
    """The same call, asking for its JSON object as streamable text."""
    schema = json.dumps(call.output_schema, separators=(",", ":"))
    return replace(call, system_prompt=call.system_prompt + TEXT_JSON_FRAME.format(schema=schema))


def json_object_in(text: Any) -> dict[str, Any] | None:
    """Parse a reply that should be one JSON object (tolerating a code fence around it)."""
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        value = json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def streaming_argv(argv: list[str]) -> list[str]:
    """Swap ``--output-format json`` for stream-json and drop ``--json-schema``."""
    out: list[str] = []
    skip = False
    for index, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg in ("--output-format", "--json-schema") and index > 2:  # 2 is the prompt
            skip = True
            if arg == "--output-format":
                out.extend(STREAM_FLAGS)
            continue
        out.append(arg)
    return out


@dataclass(slots=True)
class StreamState:
    """What the reader saw: the result line, stream liveness, and block numbering."""

    on_delta: DeltaCallback
    result: dict[str, Any] | None = None
    events: int = 0
    block: int = 0
    open_blocks: dict[int, int] = field(default_factory=dict)
    callback_failed: bool = False

    def _emit(self, block: int, chunk: str) -> None:
        if self.callback_failed or not chunk:
            return
        try:
            self.on_delta(block, chunk)
        except Exception:  # drafts are best effort; never break the model call
            self.callback_failed = True

    def _stream_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        index = event.get("index")
        if kind == "message_start":
            self.open_blocks = {}
        elif kind == "content_block_start" and isinstance(index, int):
            self.block += 1
            self.open_blocks[index] = self.block
        elif kind == "content_block_delta" and isinstance(index, int):
            delta = event.get("delta") or {}
            chunk = delta.get("text") if delta.get("type") == "text_delta" else (
                delta.get("partial_json") if delta.get("type") == "input_json_delta" else None)
            if isinstance(chunk, str):
                self._emit(self.open_blocks.get(index, self.block), chunk)

    def feed(self, line: str) -> None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return
        self.events += 1
        kind = message.get("type")
        if kind == "stream_event" and isinstance(message.get("event"), dict):
            self._stream_event(message["event"])
        elif kind == "result":
            self.result = message


def read_stream(lines: Iterable[bytes], on_delta: DeltaCallback) -> StreamState:
    """Consume NDJSON lines; returns the final state (result may be None)."""
    state = StreamState(on_delta)
    for raw in lines:
        text = raw.decode("utf-8", "replace").strip()
        if text:
            state.feed(text)
    return state


def run_streaming(
    argv: list[str], cwd: str, env: dict[str, str], timeout_s: int, on_delta: DeltaCallback
) -> tuple[dict[str, Any], int, int]:
    """Run the CLI with stream flags; return (result payload, exit code, elapsed ms).

    Raises ``StreamUnsupported`` when the CLI printed no JSON line at all, and
    ``TimeoutError`` when the call exceeds ``timeout_s`` (the process is killed).
    """
    started = time.monotonic()
    process = subprocess.Popen(  # nosec B603 - fixed argv, no shell
        streaming_argv(argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    expired = threading.Event()

    def kill() -> None:
        expired.set()
        process.kill()

    timer = threading.Timer(timeout_s, kill)
    timer.daemon = True
    timer.start()
    try:
        stdout: IO[bytes] | None = process.stdout
        state = read_stream(stdout if stdout is not None else (), on_delta)
        returncode = process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
    elapsed = int((time.monotonic() - started) * 1000)
    if expired.is_set():
        raise TimeoutError("model call timed out")
    if state.result is None:
        if state.events == 0:
            raise StreamUnsupported(f"no stream output (exit {returncode})")
        return {}, returncode, elapsed
    return state.result, returncode, elapsed
