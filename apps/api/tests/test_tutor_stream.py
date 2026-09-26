"""SSE tutor route: event sequence and error events (ADR 0013 v2)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.main import app
from apps.api.app.tutor.stream import Finished, sse, with_progress
from apps.api.tests.tutor_fakes import tutor_env
from fastapi.testclient import TestClient
from packages.models.claude_code import ModelCallError, UsageLimitError

client = TestClient(app)
ROUTE = "/v1/tutor/ask/stream"


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    with tutor_env(monkeypatch) as state:
        yield state


def events(body: dict[str, Any]) -> list[tuple[str, Any]]:
    response = client.post(ROUTE, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = []
    for frame in response.text.split("\n\n"):
        lines = [line for line in frame.split("\n") if line and not line.startswith(":")]
        if lines:
            name = lines[0].removeprefix("event: ")
            parsed.append((name, json.loads(lines[1].removeprefix("data: "))))
    return parsed


def stages(parsed: list[tuple[str, Any]]) -> list[str]:
    return [data["stage"] if name == "status" else name for name, data in parsed]


def test_stream_reports_progress_then_answer_and_done(env: dict[str, Any]) -> None:
    parsed = events({"question": "What is crazy paving?"})
    assert stages(parsed) == ["retrieving", "answering", "judging", "answer", "done"]
    answer = dict(parsed)["answer"]
    assert answer["grounding"] == "sources" and answer["judge"]["status"] == "ok"
    assert answer["segments"][0]["support"] == "supported"
    assert dict(parsed)["done"]["message_id"] == answer["message_id"]
    assert UUID(answer["thread_id"]) in env["repo"].threads
    assert env["session"].events == ["rollback", f"tenant:{env['session'].events[1][7:]}",
                                     "commit"]


def test_stream_reports_web_research_when_coverage_is_partial(env: dict[str, Any]) -> None:
    env["transport"].output = {"coverage": "partial", "segments": [
        {"text": "PAP shows crazy paving.", "sources": ["S1"]}]}
    parsed = events({"question": "What is crazy paving?"})
    assert stages(parsed) == ["retrieving", "answering", "web_research", "judging",
                              "answer", "done"]


def test_stream_without_cli_is_a_503_error_event(env: dict[str, Any]) -> None:
    env["transport"] = None
    parsed = events({"question": "What is crazy paving?"})
    assert [name for name, _ in parsed] == ["error"]
    assert parsed[0][1]["status"] == 503 and "Claude Code CLI" in parsed[0][1]["detail"]


@pytest.mark.parametrize(("error", "status"), [(UsageLimitError("x"), 429),
                                               (ModelCallError("y"), 502)])
def test_stream_model_failures_are_error_events(
    env: dict[str, Any], error: Exception, status: int
) -> None:
    env["transport"].output = error
    parsed = events({"question": "What is crazy paving?"})
    assert stages(parsed) == ["retrieving", "answering", "error"]
    assert parsed[-1][1]["status"] == status
    assert "commit" not in env["session"].events


def test_stream_unknown_thread_is_a_404_error_event(env: dict[str, Any]) -> None:
    parsed = events({"question": "What is it?", "thread_id": str(uuid4())})
    assert stages(parsed) == ["retrieving", "error"] and parsed[-1][1]["status"] == 404
    assert env["transport"].calls == []


def test_stream_request_validation_is_plain_422(env: dict[str, Any]) -> None:
    assert client.post(ROUTE, json={"question": "x"}).status_code == 422


def test_sse_frame_format() -> None:
    assert sse("status", {"stage": "a\nb"}) == 'event: status\ndata: {"stage":"a\\nb"}\n\n'


def _collect(work: Callable[[Callable[[str], None]], Any], heartbeat: float) -> list[Any]:
    async def run() -> list[Any]:
        return [item async for item in with_progress(work, heartbeat)]

    return asyncio.run(run())


def test_with_progress_yields_stages_heartbeats_and_result() -> None:
    def work(report: Callable[[str], None]) -> int:
        report("answering")
        time.sleep(0.2)
        report("judging")
        return 7

    items = _collect(work, heartbeat=0.05)
    assert [i for i in items if isinstance(i, str)] == ["answering", "judging"]
    assert None in items and items[-1] == Finished(7)


def test_with_progress_propagates_work_errors() -> None:
    def work(report: Callable[[str], None]) -> int:
        report("answering")
        raise UsageLimitError("limit")

    with pytest.raises(UsageLimitError):
        _collect(work, heartbeat=1.0)
