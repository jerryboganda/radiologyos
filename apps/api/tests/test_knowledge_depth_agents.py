"""Knowledge depth agents: prompts, schemas, fixture, and worker steps with fakes.

No database or model: the worker steps run against a statement-recording fake
session and a scripted transport (ADR 0030).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.worker.app.knowledge import concept_notes, conflict_agent, resolver
from apps.worker.app.knowledge.budget import Budget
from apps.worker.app.knowledge.notes import Continue
from apps.worker.app.knowledge.runtime import KnowledgeDeps
from evals.contracts import load_eval_fixtures
from packages.knowledge.agents import ConceptNote, ConflictVerdict, ResolverDecision
from packages.library.parse_models import inline_schema
from packages.models.claude_code import ModelCall, ModelResult
from packages.models.gateway import build_call, load_agent

ROOT = Path(__file__).resolve().parents[3]
AGENTS = {
    "concept_synthesis": ("extract", ConceptNote),
    "concept_resolver": ("reason", ResolverDecision),
    "claim_conflict": ("reason", ConflictVerdict),
}


class FakeTransport:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[ModelCall] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        return ModelResult(output=self.output, duration_ms=1, cost_usd=0.0)


class FakeSession:
    def __init__(self) -> None:
        self.sql: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        self.sql.append((" ".join(str(statement).split()), params or {}))
        return self

    def scalar_one_or_none(self) -> Any:
        return uuid4()


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_depth_agents_use_named_routes_generated_schemas_and_fixture(name: str) -> None:
    route, model = AGENTS[name]
    agent = load_agent(name)
    assert agent.prompt.route == route and agent.prompt.effort == "medium"
    assert agent.output_model is model and agent.schema == inline_schema(model)
    assert agent.prompt.fixture == "evals/fixtures/knowledge_v3.json"
    assert "untrusted" in agent.prompt.system_prompt
    assert build_call(agent, "p").tools == ()


def test_v3_fixture_is_synthetic_and_covers_every_depth_agent() -> None:
    fixture = load_eval_fixtures(ROOT / "evals" / "fixtures" / "knowledge_v3.json")
    assert fixture.data_class == "synthetic"
    assert {c.prompt.split("/")[0] for c in fixture.cases} == set(AGENTS)
    for case in fixture.cases:
        assert (ROOT / "packages" / "prompts" / case.prompt).is_file()
        assert case.route.value == AGENTS[case.prompt.split("/")[0]][0]
    labels = {str(c.expected.get("label")) for c in fixture.cases if "label" in c.expected}
    assert labels == {"conflict", "context", "same"}


def test_budget_raises_continue_after_its_units() -> None:
    budget = Budget(2)
    budget.spend()
    budget.spend()
    with pytest.raises(Continue):
        budget.spend()
    assert budget.spent == 2


def _conflict_row() -> dict[str, Any]:
    return {"id": uuid4(), "a_id": uuid4(), "b_id": uuid4(), "kind": "numeric",
            "description": "Numeric disagreement (years)", "concept_name": "Synthetic X",
            "a_statement": "X under 20 years", "a_span": "under 20 years",
            "a_citation": {"source_title": "Book A", "page_from": 1, "page_to": 1},
            "b_statement": "X over 20 years", "b_span": "over 20 years", "b_citation": None}


async def test_confident_context_verdict_closes_the_conflict_keeping_both_claims() -> None:
    session, row = FakeSession(), _conflict_row()
    verdict = ConflictVerdict(label="context", confidence=0.9, rationale="[A] long bones, [B] "
                              "flat bones.", cites=["A", "B"], context="bone type")
    assert await conflict_agent.apply_verdict(session, row, verdict) == "auto_resolve"
    statements = [s for s, _ in session.sql]
    assert statements[0].startswith("UPDATE knowledge_conflicts SET ai_label")
    assert statements[1].startswith("UPDATE knowledge_conflicts SET status = 'resolved'")
    assert session.sql[1][1]["p"] is None and session.sql[1][1]["u"] is None
    assert [p["s"] for s, p in session.sql[2:]] == ["active", "active"]
    prompt = conflict_agent.conflict_prompt(row)
    assert "[A] X under 20 years" in prompt and "Source: Book A, pp. 1-1" in prompt


async def test_true_or_unsure_conflict_stays_open_with_the_rationale() -> None:
    for label, confidence in (("conflict", 0.99), ("same", 0.5)):
        session = FakeSession()
        verdict = ConflictVerdict(label=label, confidence=confidence, rationale="[A] vs [B].",
                                  cites=["A"], context="")
        assert await conflict_agent.apply_verdict(session, _conflict_row(), verdict) == (
            "keep_open")
        assert len(session.sql) == 1


def _concept(name: str, claims: int) -> dict[str, Any]:
    return {"id": uuid4(), "name": name, "normalized_name": name.lower(), "aliases": [],
            "alias_keys": [], "claim_count": claims, "created_at": "2026-01-01",
            "concept_type": "disease", "merged_into": None}


async def test_resolver_applies_only_confident_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    applied: list[tuple[Any, Any]] = []

    async def fake_record(*args: Any) -> UUID:
        return uuid4()

    async def fake_apply(_s: Any, _m: Any, survivor: Any, merged: Any) -> dict[str, Any]:
        applied.append((survivor, merged))
        return {}

    monkeypatch.setattr(resolver.merges, "record_decision", fake_record)
    monkeypatch.setattr(resolver.merges, "apply_merge", fake_apply)
    big, small = _concept("Appendiceal mucocele", 5), _concept("Mucocele of appendix", 1)
    sure = ResolverDecision(decision="merge", parent="", confidence=0.9, rationale="Same.")
    unsure = sure.model_copy(update={"confidence": 0.6})
    assert await resolver.apply_decision(None, uuid4(), uuid4(), (small, big, 0.85),
                                         sure) == "merge"
    assert applied == [(big["id"], small["id"])]
    assert await resolver.apply_decision(None, uuid4(), uuid4(), (small, big, 0.85),
                                         unsure) == "review"
    assert len(applied) == 1
    assert resolver.band_similarity(big, big) == 1.0
    assert "[A] Appendiceal mucocele (disease)" in resolver.summary("A", big, [])


def _deps(output: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
          stored: list[Any]) -> KnowledgeDeps:
    @asynccontextmanager
    async def fake_tx(_engine: Any, _tenant: Any) -> AsyncIterator[None]:
        yield None

    async def fake_store(_s: Any, _t: Any, _u: Any, _p: Any, checked: Any, _v: int) -> None:
        stored.append(checked)

    monkeypatch.setattr(concept_notes, "tenant_tx", fake_tx)
    monkeypatch.setattr(concept_notes, "_store", fake_store)
    return KnowledgeDeps(engine=None, transport=FakeTransport(output))  # type: ignore[arg-type]


def _prepared() -> concept_notes.Prepared:
    claim = {"id": uuid4(), "status": "active", "importance": 5, "claim_type": "definition",
             "modality": "", "statement": "Synthetic PAP fills alveoli with lipoprotein.",
             "evidence_span": "fills alveoli with lipoprotein"}
    return concept_notes.Prepared({"id": uuid4(), "name": "PAP", "concept_type": "disease",
                                   "aliases": []}, [claim], [], "0" * 64)


def _note(*sentences: dict[str, Any]) -> dict[str, Any]:
    return {"definition": list(sentences), "imaging": [], "differentials": [], "pearls": [],
            "pitfalls": []}


async def test_synthesis_stores_only_cited_supported_sentences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[Any] = []
    output = _note({"text": "Synthetic PAP fills alveoli with lipoprotein.", "cites": ["C1"]},
                   {"text": "It is caused by 3 genes.", "cites": ["C1"]})
    deps = _deps(output, monkeypatch, stored)
    assert await concept_notes.write(deps, uuid4(), uuid4(), _prepared(), 1) == "stored"
    [checked] = stored
    assert checked.kept == 1 and checked.dropped == 1
    assert checked.body["definition"][0]["text"].startswith("Synthetic PAP fills")


async def test_synthesis_fails_closed_when_nothing_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[Any] = []
    output = _note({"text": "Honeycombing dominates the lower zones.", "cites": ["C1"]},
                   {"text": "Synthetic PAP fills alveoli with lipoprotein.", "cites": ["C7"]})
    deps = _deps(output, monkeypatch, stored)
    assert await concept_notes.write(deps, uuid4(), uuid4(), _prepared(), 1) == "unsupported"
    assert stored == []
