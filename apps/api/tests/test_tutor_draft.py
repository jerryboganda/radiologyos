"""Draft text from a streaming tutor answer, and grounding after it (ADR 0025)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from apps.api.tests.tutor_fakes import ScriptedTransport
from packages.models.claude_code import ModelCall, ModelResult
from packages.tutor.draft import DraftOp, DraftTracker, diff_ops, draft_texts
from packages.tutor.grounding import excerpts_from_hits
from packages.tutor.orchestrator import answer_question

FULL = json.dumps({"coverage": "full", "segments": [
    {"text": "PAP shows \"crazy paving\" — GGO.", "sources": ["S1", "S2"]},
    {"text": "It is always fatal.", "sources": ["S1"]},
]})


@pytest.mark.parametrize(("buffer", "expected"), [
    ("", []),
    ('{"coverage": "full"', []),
    ('{"segments": [', []),
    ('{"segments": [{"te', [""]),
    ('{"segments": [{"text": "PAP sh', ["PAP sh"]),
    ('{"segments": [{"text": "a\\', ["a"]),
    ('{"segments": [{"text": "a\\u00', ["a"]),
    ('{"segments": [{"text": "a\\u00e9b", "sources": ["S1"]}, {"sources": ["S2"], "text": "c',
     ["aéb", "c"]),
    ('{"segments": [{"sources": ["text"], "text": "x"}], "pages": [{"summary": "no"}]}',
     ["x"]),
])
def test_draft_texts_reads_partial_json(buffer: str, expected: list[str]) -> None:
    assert draft_texts(buffer) == expected


def test_draft_texts_of_every_prefix_never_fails_and_ends_complete() -> None:
    for end in range(len(FULL) + 1):
        draft_texts(FULL[:end])
    assert draft_texts(FULL) == ['PAP shows "crazy paving" — GGO.', "It is always fatal."]


def test_diff_ops_appends_replaces_and_shrinks() -> None:
    assert diff_ops("sources", ["ab"], ["abc", "d"]) == [
        DraftOp("sources", segment=0, append="c"), DraftOp("sources", segment=1, text="d")]
    assert diff_ops("web", ["abc"], ["xyz"]) == [DraftOp("web", segment=0, text="xyz")]
    assert diff_ops("web", ["a", "b"], ["a"]) == [DraftOp("web", count=1)]
    assert DraftOp("web", segment=0, append="c").as_event() == {
        "phase": "web", "segment": 0, "append": "c"}


def test_tracker_throttles_and_follows_the_json_block() -> None:
    ops: list[DraftOp] = []
    now = [0.0]
    tracker = DraftTracker("sources", ops.append, interval=1.0, clock=lambda: now[0])
    tracker(1, "Thinking about segments")  # narration without a JSON array: ignored
    now[0] = 2.0
    tracker(2, '{"segments": [{"text": "PAP')
    tracker(2, ' shows')  # within the interval: buffered
    assert ops == [DraftOp("sources", segment=0, text="PAP")]
    tracker.flush()
    assert ops[-1] == DraftOp("sources", segment=0, append=" shows")


class StreamingScripted(ScriptedTransport):
    """Streams the source answer's JSON in small chunks, then returns it."""

    def run_stream(self, call: ModelCall, on_delta: Any) -> ModelResult:
        output = self.web if "WebSearch" in call.tools else self.source
        text = json.dumps(output)
        for start in range(0, len(text), 7):
            on_delta(1, text[start:start + 7])
        self.calls.append(call)
        return ModelResult(output=output, duration_ms=1, cost_usd=0.0)


def _judge_second_unsupported(call: ModelCall) -> dict[str, Any]:
    return {"verdicts": [{"segment": 1, "verdict": "supported", "reason": "S1."},
                         {"segment": 2, "verdict": "unsupported", "reason": "Not stated."}]}


def test_drafts_stream_but_the_answer_is_still_grounded_and_judged() -> None:
    excerpts = excerpts_from_hits([
        {"id": uuid4(), "source_id": uuid4(), "source_title": "Synthetic deck", "page_from": i,
         "page_to": i, "heading": "", "text": "Crazy paving in PAP.", "block_refs": []}
        for i in (1, 2)])
    transport = StreamingScripted(source=json.loads(FULL), judge=_judge_second_unsupported)
    drafts: list[DraftOp] = []
    answer = answer_question(transport, "What is crazy paving?", excerpts, allow_web=False,
                             on_draft=drafts.append)
    streamed: dict[int, str] = {}
    for op in drafts:
        assert op.phase == "sources"
        if op.segment is not None:
            streamed[op.segment] = (op.text if op.text is not None
                                    else streamed[op.segment] + (op.append or ""))
    assert streamed[1] == "It is always fatal."  # the draft showed it ...
    assert [s.text for s in answer.segments] == ['PAP shows "crazy paving" — GGO.']
    assert answer.dropped_segments == 1  # ... the judged answer removed it
    assert len(transport.judge_calls) == 1
