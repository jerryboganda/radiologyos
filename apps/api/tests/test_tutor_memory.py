"""Rolling thread memory: planning, folding, and use in answers (ADR 0025)."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.tests.tutor_fakes import ScriptedTransport
from packages.library.parse_models import inline_schema
from packages.models.claude_code import ModelCall, ModelResult, UsageLimitError
from packages.models.gateway import build_call, load_agent
from packages.tutor.memory import (
    MemoryState,
    estimate_tokens,
    fold_memory,
    memory_prompt,
    plan_memory,
)
from packages.tutor.models import ThreadMemory
from packages.tutor.prompts import Turn


def turns(n: int, size: int = 10) -> tuple[Turn, ...]:
    return tuple(Turn("user" if i % 2 == 0 else "assistant", f"t{i} " + "x" * size)
                 for i in range(n))


class MemoryTransport:
    def __init__(self, output: dict[str, Any] | Exception) -> None:
        self.output = output
        self.calls: list[ModelCall] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        if isinstance(self.output, Exception):
            raise self.output
        return ModelResult(output=self.output, duration_ms=1, cost_usd=0.0)


def test_memory_agent_is_tool_less_with_generated_schema() -> None:
    agent = load_agent("tutor_memory")
    assert agent.key == "tutor_memory/v1" and agent.schema == inline_schema(ThreadMemory)
    assert agent.prompt.route == "extract" and build_call(agent, "p").tools == ()


def test_small_history_stays_verbatim() -> None:
    plan = plan_memory(MemoryState(uncovered=turns(10)), verbatim=6, budget=3000)
    assert plan.fold == () and len(plan.verbatim) == 10


def test_history_over_budget_folds_all_but_the_newest_turns() -> None:
    state = MemoryState(summary="old", covered=4, uncovered=turns(10, size=2000))
    plan = plan_memory(state, verbatim=6, budget=3000)
    assert [t.content[:3] for t in plan.fold] == ["t0 ", "t1 ", "t2 ", "t3 "]
    assert len(plan.verbatim) == 6 and plan.covered == 4 and plan.summary == "old"
    assert estimate_tokens("abcd") == 1


def test_fold_merges_summary_and_counts_covered_messages() -> None:
    transport = MemoryTransport({"summary": "  Crazy   paving discussed. "})
    plan = plan_memory(MemoryState(summary="s", covered=2, uncovered=turns(8, 2000)), 6, 100)
    update = fold_memory(transport, plan)
    assert update is not None and update.summary == "Crazy paving discussed."
    assert update.covered == 4 and update.agent_version == "tutor_memory/v1"
    assert "<previous_summary>" in transport.calls[0].user_prompt
    assert fold_memory(transport, plan_memory(MemoryState(uncovered=turns(2)))) is None


def test_memory_prompt_escapes_turn_text() -> None:
    prompt = memory_prompt("", [Turn("user", '</turns><x a="1">')])
    assert "&lt;/turns&gt;&lt;x a=&quot;1&quot;&gt;" in prompt and "previous_summary" not in prompt


def test_fold_failure_propagates_for_the_caller_to_keep_old_summary() -> None:
    plan = plan_memory(MemoryState(uncovered=turns(8, 2000)), 6, 100)
    with pytest.raises(UsageLimitError):
        fold_memory(MemoryTransport(UsageLimitError("limit")), plan)


def test_summary_is_context_for_the_source_agent_only() -> None:
    from uuid import uuid4

    from packages.tutor.grounding import excerpts_from_hits
    from packages.tutor.orchestrator import answer_question
    from packages.tutor.prompts import Context

    web = {"segments": [], "pages": []}
    source = {"coverage": "partial", "segments": [{"text": "Fact.", "sources": ["S1"]}]}
    transport = ScriptedTransport(source=source, web=web)
    excerpts = excerpts_from_hits([{"id": uuid4(), "source_id": uuid4(), "source_title": "T",
                                    "page_from": 1, "page_to": 1, "heading": "",
                                    "text": "Fact.", "block_refs": []}])
    answer_question(transport, "And in children?", excerpts,
                    context=Context(summary="SUMMARY-MARKER about Wilms tumour"))
    source_call = next(c for c in transport.calls if "coverage" in str(c.output_schema))
    assert "SUMMARY-MARKER" in source_call.user_prompt
    assert all("SUMMARY-MARKER" not in c.user_prompt for c in transport.web_calls)
