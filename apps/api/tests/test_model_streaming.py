"""Token streaming in the Claude Code transport and the gateway fallback (ADR 0025).

No real model: the CLI is replaced by a tiny Python script that prints
synthetic stream-json lines, and the gateway is exercised with fake transports.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from packages.models.claude_code import (
    ModelCall,
    ModelCallError,
    ModelResult,
    UsageLimitError,
    _parse_payload,
)
from packages.models.claude_stream import (
    StreamOutputInvalid,
    StreamUnsupported,
    json_object_in,
    read_stream,
    run_streaming,
    streaming_argv,
    text_json_call,
)
from packages.models.gateway import run_agent
from packages.tutor.models import ThreadMemory

RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 5,
          "total_cost_usd": 0.0, "result": '{"summary": "Crazy paving."}'}


def _line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload) + "\n").encode()


def _event(event: dict[str, Any]) -> bytes:
    return _line({"type": "stream_event", "event": event})


def _delta(index: int, kind: str, value: str) -> bytes:
    key = "text" if kind == "text_delta" else "partial_json"
    return _event({"type": "content_block_delta", "index": index,
                   "delta": {"type": kind, key: value}})


def _call(**overrides: Any) -> ModelCall:
    values: dict[str, Any] = {"model": "m", "effort": "high", "system_prompt": "sys",
                              "user_prompt": "user", "output_schema": {"type": "object"}}
    return ModelCall(**{**values, **overrides})


def test_read_stream_numbers_blocks_across_messages_and_keeps_the_result() -> None:
    seen: list[tuple[int, str]] = []
    lines = [
        _line({"type": "system", "subtype": "init"}),
        _event({"type": "message_start"}),
        _event({"type": "content_block_start", "index": 0}),
        _delta(0, "text_delta", "Let me search"),
        _event({"type": "message_start"}),
        _event({"type": "content_block_start", "index": 0}),
        _delta(0, "input_json_delta", '{"segments": ['),
        b"not json\n",
        _line(RESULT),
    ]
    state = read_stream(lines, lambda block, chunk: seen.append((block, chunk)))
    assert seen == [(1, "Let me search"), (2, '{"segments": [')]
    assert state.result == RESULT and state.events == 8


def test_a_failing_delta_callback_never_breaks_the_call() -> None:
    def boom(_block: int, _chunk: str) -> None:
        raise RuntimeError("client went away")

    state = read_stream([_event({"type": "content_block_start", "index": 0}),
                         _delta(0, "text_delta", "a"), _delta(0, "text_delta", "b"),
                         _line(RESULT)], boom)
    assert state.callback_failed and state.result == RESULT


def test_streaming_argv_swaps_output_format_and_drops_the_schema() -> None:
    argv = ["claude", "-p", "--json-schema", "--output-format", "json", "--json-schema", "{}",
            "--tools", ""]
    assert streaming_argv(argv) == [
        "claude", "-p", "--json-schema", "--output-format", "stream-json", "--verbose",
        "--include-partial-messages", "--tools", ""]


def test_text_json_call_carries_the_schema_in_the_system_prompt() -> None:
    call = text_json_call(_call(output_schema={"type": "object", "required": ["a"]}))
    assert call.system_prompt.startswith("sys")
    assert '{"type":"object","required":["a"]}' in call.system_prompt
    assert "no code fences" in call.system_prompt


@pytest.mark.parametrize(("text", "expected"), [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": {"b": [1]}}\n```', {"a": {"b": [1]}}),
    ("no json here", None),
    ("[1, 2]", None),
    ('{"a": ', None),
    (None, None),
])
def test_json_object_in(text: Any, expected: Any) -> None:
    assert json_object_in(text) == expected


def test_text_json_result_is_parsed_and_errors_still_map() -> None:
    result = _parse_payload(RESULT, 9, text_json=True)
    assert result.output == {"summary": "Crazy paving."} and result.duration_ms == 5
    with pytest.raises(StreamOutputInvalid):
        _parse_payload({**RESULT, "result": "sorry"}, 9, text_json=True)
    with pytest.raises(UsageLimitError):
        _parse_payload({"type": "result", "subtype": "error", "is_error": True,
                        "api_error_status": 429}, 9, text_json=True)


FAKE_CLI = """
import json, sys, time
mode = sys.argv[1]
if mode == "silent":
    sys.exit(2)
if mode == "slow":
    time.sleep(30)
assert "--json-schema" not in sys.argv and "stream-json" in sys.argv, sys.argv
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
print(json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "index": 0}}))
for part in ['{"summ', 'ary": "ok"}']:
    print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
          "index": 0, "delta": {"type": "text_delta", "text": part}}}), flush=True)
if mode == "ok":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": '{"summary": "ok"}'}))
"""


def _run_fake(tmp_path: Path, mode: str, timeout: int = 20) -> tuple[Any, list[str]]:
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    chunks: list[str] = []
    argv = [sys.executable, str(script), mode, "--output-format", "json", "--json-schema", "{}"]
    env = dict(os.environ)
    out = run_streaming(argv, str(tmp_path), env, timeout, lambda _b, c: chunks.append(c))
    return out, chunks


def test_run_streaming_reads_a_real_subprocess(tmp_path: Path) -> None:
    (payload, code, _elapsed), chunks = _run_fake(tmp_path, "ok")
    assert code == 0 and payload["result"] == '{"summary": "ok"}'
    assert "".join(chunks) == '{"summary": "ok"}'


def test_run_streaming_signals_no_stream_and_no_result(tmp_path: Path) -> None:
    with pytest.raises(StreamUnsupported):
        _run_fake(tmp_path, "silent")
    (payload, _code, _elapsed), chunks = _run_fake(tmp_path, "noresult")
    assert payload == {} and chunks


def test_run_streaming_kills_a_call_past_its_timeout(tmp_path: Path) -> None:
    with pytest.raises(TimeoutError):
        _run_fake(tmp_path, "slow", timeout=1)


class StreamingFake:
    """run_stream behaves per ``stream``; run returns ``plain``."""

    def __init__(self, stream: Any, plain: dict[str, Any] | None = None) -> None:
        self.stream, self.plain = stream, plain
        self.runs = 0

    def run(self, call: ModelCall) -> ModelResult:
        self.runs += 1
        if self.plain is None:
            raise AssertionError("plain call not expected")
        return ModelResult(output=self.plain, duration_ms=1, cost_usd=0.0)

    def run_stream(self, call: ModelCall, on_delta: Any) -> ModelResult:
        on_delta(1, '{"summary": "dr')
        if isinstance(self.stream, Exception):
            raise self.stream
        return ModelResult(output=self.stream, duration_ms=1, cost_usd=0.0)


def test_gateway_streams_and_validates_without_a_second_call() -> None:
    fake, deltas = StreamingFake({"summary": "streamed"}), []
    parsed, _ = run_agent(fake, "tutor_memory", "p",
                          on_delta=lambda b, c: deltas.append(c))
    assert isinstance(parsed, ThreadMemory) and parsed.summary == "streamed"
    assert fake.runs == 0 and deltas == ['{"summary": "dr']


@pytest.mark.parametrize("stream", [StreamUnsupported("old cli"), StreamOutputInvalid("prose"),
                                    {"summary": 3}])
def test_gateway_falls_back_to_one_schema_enforced_call(stream: Any) -> None:
    fake = StreamingFake(stream, plain={"summary": "plain"})
    parsed, _ = run_agent(fake, "tutor_memory", "p", on_delta=lambda b, c: None)
    assert parsed.summary == "plain" and fake.runs == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize("error", [UsageLimitError("limit"), ModelCallError("failed")])
def test_gateway_never_retries_a_model_failure(error: Exception) -> None:
    fake = StreamingFake(error, plain={"summary": "plain"})
    with pytest.raises(type(error)):
        run_agent(fake, "tutor_memory", "p", on_delta=lambda b, c: None)
    assert fake.runs == 0


def test_gateway_without_on_delta_never_streams() -> None:
    fake = StreamingFake(AssertionError("must not stream"), plain={"summary": "plain"})
    parsed, _ = run_agent(fake, "tutor_memory", "p")
    assert parsed.summary == "plain" and fake.runs == 1  # type: ignore[attr-defined]
