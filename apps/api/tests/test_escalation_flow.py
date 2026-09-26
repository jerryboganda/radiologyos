"""Owner flow (ADR 0037): Luna max -> Sol high -> Opus 5.5 high only after asking."""

from __future__ import annotations

from typing import Any

import pytest
from packages.models.claude_code import (
    ModelCall,
    ModelCallError,
    ModelResult,
    OwnerApprovalRequired,
    UsageLimitError,
)
from packages.models.gateway import build_calls, load_agent, owner_approved, run_agent, soft

PAGE = {"page_type": "text", "blocks": [], "figures": [], "topics": []}
BULK = ("page_parse", "image_case", "knowledge_extract", "topic_classify", "paper_topics",
        "concept_synthesis", "concept_resolver", "claim_conflict")


class _ByModel:
    backends = ("codex", "claude_code")

    def __init__(self, **outcomes: Any) -> None:
        self.outcomes, self.models = outcomes, []

    def run(self, call: ModelCall) -> ModelResult:
        self.models.append(call.model)
        outcome = self.outcomes[call.model.replace("-", "_")]
        if isinstance(outcome, Exception):
            raise outcome
        return ModelResult(output=outcome, duration_ms=1, cost_usd=0.0, backend=call.backend)


@pytest.fixture(autouse=True)
def not_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BULK_CLAUDE_FALLBACK_APPROVED", raising=False)


def _every(**kw: Any) -> _ByModel:
    return _ByModel(**{"gpt_6_luna": PAGE, "gpt_6_sol": PAGE, "claude_opus_5_5": PAGE, **kw})


def test_final_flow_for_every_bulk_agent() -> None:
    for name in BULK:
        calls = build_calls(load_agent(name), "p")
        assert [(c.model, c.effort, c.requires_approval) for c in calls] == [
            ("gpt-6-luna", "max", False), ("gpt-6-sol", "high", False),
            ("claude-opus-5-5", "high", True)], name


def test_a_weak_answer_goes_to_sol_then_waits_for_the_owner_with_the_best_so_far() -> None:
    transport = _every()
    parsed, result = run_agent(transport, "page_parse", "p", accept=lambda _: "low_coverage")
    assert transport.models == ["gpt-6-luna", "gpt-6-sol"]  # Opus never called
    assert result.escalation == "low_coverage" and parsed.model_dump()["page_type"] == "text"


def test_a_second_opinion_reason_stops_at_sol_without_asking() -> None:
    transport = _every()
    _, result = run_agent(transport, "page_parse", "p", accept=lambda _: soft("low_confidence"))
    assert transport.models == ["gpt-6-luna", "gpt-6-sol"] and result.escalation is None


def test_sol_fixing_lunas_answer_needs_nothing_from_the_owner() -> None:
    transport = _every()
    answers = iter([soft("doubt"), None])
    _, result = run_agent(transport, "page_parse", "p", accept=lambda _: next(answers))
    assert transport.models == ["gpt-6-luna", "gpt-6-sol"] and result.escalation is None


def test_no_answer_at_all_is_reported_for_the_owner_not_paused() -> None:
    transport = _every(gpt_6_luna=ModelCallError("x"), gpt_6_sol=ModelCallError("y"))
    with pytest.raises(OwnerApprovalRequired) as raised:
        run_agent(transport, "page_parse", "p")
    assert not isinstance(raised.value, UsageLimitError)  # the job carries on
    assert transport.models == ["gpt-6-luna", "gpt-6-sol"]


def test_approved_items_go_straight_to_opus() -> None:
    transport = _every()
    with owner_approved("page_parse"):
        _, result = run_agent(transport, "page_parse", "p", accept=lambda _: "low_coverage")
    assert transport.models == ["claude-opus-5-5"] and result.escalation is None
    run_agent(transport, "page_parse", "p")  # the approval ends with the block
    assert transport.models[-1] == "gpt-6-luna"
