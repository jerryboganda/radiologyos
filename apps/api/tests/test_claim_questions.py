"""Claim-based SBA generation (question_generate/v2, ADR 0029): inputs, checks, routes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from apps.api.app.api import assessment as api
from apps.api.app.assessment import claim_basis, dedupe, generation, retrieval
from apps.api.app.assessment import store as question_store
from apps.api.app.main import app
from apps.api.tests.test_assessment_api import PASS, FakeTransport, client  # noqa: F401
from apps.api.tests.test_assessment_validation import EXCERPTS, sba_item
from apps.api.tests.test_knowledge_cards import claim
from fastapi.testclient import TestClient
from packages.assessment import agents
from packages.assessment.claim_questions import (
    Neighbour,
    build_material,
    claim_problems,
    graph_distractors,
    render_neighbours,
)
from packages.models.claude_code import ModelCall, ModelResult
from packages.models.gateway import load_agent

NEIGHBOURS = [Neighbour("Pulmonary oedema", ("cardiogenic oedema",), "differential_of"),
              Neighbour("Pneumocystis pneumonia", ("PCP",), "differential_of"),
              Neighbour("Sarcoidosis", (), "sibling")]


def _rows(*names: str) -> list[dict[str, Any]]:
    return [{"id": uuid4(), "name": n, "aliases": [], "relation": "differential_of"}
            for n in names]


def _material() -> tuple[list[Any], list[Neighbour]]:
    built = build_material([claim(), claim(), claim()], _rows("Pulmonary oedema", "ARDS"),
                           [claim(concept_name="Pulmonary oedema")])
    assert built is not None
    return built


def test_material_needs_enough_claims_and_neighbours() -> None:
    assert build_material([claim(), claim()], _rows("A", "B"), []) is None
    assert build_material([claim()] * 3, _rows("Only one"), []) is None
    excerpts, neighbours = _material()
    assert [e.ref for e in excerpts] == ["C1", "C2", "C3", "C4"]
    assert excerpts[0].citation["kind"] == "claim" and excerpts[0].citation["block_refs"]
    assert "Evidence: crazy paving on HRCT" in excerpts[0].text
    assert excerpts[3].heading.startswith("Neighbour:")
    assert [n.name for n in neighbours] == ["Pulmonary oedema", "ARDS"]


def test_one_claim_per_neighbour_concept() -> None:
    concept = uuid4()
    excerpts, _ = build_material([claim()] * 3, _rows("A", "B"),
                                 [claim(concept_id=concept), claim(concept_id=concept)]) or ([], [])
    assert len(excerpts) == 4


def test_graph_distractors_match_names_and_aliases_not_the_key() -> None:
    item = sba_item()  # options: PAP (key), oedema, PCP, ARDS, sarcoidosis
    assert graph_distractors(item, NEIGHBOURS) == 3
    assert claim_problems(item, NEIGHBOURS) == []
    lone = [Neighbour("Pulmonary oedema", (), "differential_of")]
    assert claim_problems(item, lone) == ["too_few_graph_distractors"]
    keyed = [Neighbour("Pulmonary alveolar proteinosis", (), "sibling")] + lone
    assert graph_distractors(item, keyed) == 1  # the key never counts
    assert "- Pneumocystis pneumonia (also: PCP) [differential_of]" in render_neighbours(
        NEIGHBOURS)


class PromptSpy(FakeTransport):
    def __init__(self, outputs: dict[str, list[Any]]) -> None:
        super().__init__(outputs)
        self.system: list[str] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.system.append(call.system_prompt)
        return super().run(call)


def _generated(*items: Any) -> dict[str, Any]:
    return {"items": [item.model_dump() for item in items]}


def test_claim_path_uses_v2_and_chunk_path_stays_on_v1() -> None:
    assert load_agent("question_generate").key == "question_generate/v2"
    assert load_agent("question_generate").schema == load_agent("question_generate", 1).schema
    v1 = load_agent("question_generate", 1).prompt.system_prompt
    v2 = load_agent("question_generate", 2).prompt.system_prompt
    spy = PromptSpy({"question_generate": [_generated(sba_item())], "question_check": [PASS]})
    generation.generate_items(spy, EXCERPTS, "sba", "frcr", 1, None)
    assert spy.system[0] == v1
    claim_item = sba_item(citations=["C1"], options=[
        {"text": t, "explanation": "why", "citations": ["C1"]}
        for t in ("Pulmonary alveolar proteinosis", "Pulmonary oedema", "Pneumocystis pneumonia",
                  "ARDS", "Sarcoidosis")])
    excerpts, _ = _material()
    spy = PromptSpy({"question_generate": [_generated(claim_item)], "question_check": [PASS]})
    outcome = generation.generate_claim_items(spy, excerpts, NEIGHBOURS, "frcr", 1, "PAP")
    assert spy.system[0] == v2 and "<neighbours>" in agents.claim_prompt(
        excerpts, "- X", "frcr", 1, "PAP")
    row = outcome.items[0]
    assert row["status"] == "active" and row["agent_version"].startswith("question_generate/v2")
    assert row["quality"]["basis"] == "claims" and row["quality"]["graph_distractors"] == 3
    assert row["citations"][0]["kind"] == "claim"
    assert all(o["citations"][0]["claim_id"] for o in row["options"])


def test_claim_items_without_graph_distractors_are_rejected_before_checking() -> None:
    excerpts, _ = _material()
    item = sba_item(citations=["C1"], options=[
        {"text": t, "explanation": "why", "citations": ["C2"]}
        for t in ("PAP", "Silicosis", "Asbestosis", "Berylliosis", "Talcosis")])
    fake = FakeTransport({"question_generate": [_generated(item)], "question_check": []})
    outcome = generation.generate_claim_items(fake, excerpts, NEIGHBOURS, "frcr", 1, "PAP")
    assert outcome.items == []
    assert outcome.rejected == [{"index": 0, "reasons": ["too_few_graph_distractors"]}]
    assert fake.calls == ["question_generate"]


def _stub_generation(monkeypatch: pytest.MonkeyPatch, basis: list[str]) -> None:
    def claims(*_: Any) -> generation.GenerationResult:
        basis.append("claims")
        return generation.GenerationResult()

    def chunks(*_: Any) -> generation.GenerationResult:
        basis.append("chunks")
        return generation.GenerationResult()

    async def gather(*_: Any, **__: Any) -> list[Any]:
        return EXCERPTS

    async def embed(*_: Any) -> tuple[list[Any], str]:
        return [], ""

    async def vector(*_: Any) -> None:
        return None

    async def get_questions(*_: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(api, "set_database_tenant", vector)
    monkeypatch.setattr(question_store, "get_questions", get_questions)
    monkeypatch.setattr(generation, "generate_claim_items", claims)
    monkeypatch.setattr(generation, "generate_items", chunks)
    monkeypatch.setattr(retrieval, "gather_excerpts", gather)
    monkeypatch.setattr(dedupe, "embed_stems", embed)
    monkeypatch.setattr(api, "query_vector", vector)


def _material_stub(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    async def material(*_: Any) -> Any:
        return value

    monkeypatch.setattr(claim_basis, "claim_material", material)


def test_generate_route_picks_claims_then_falls_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    app.dependency_overrides[api.get_transport] = lambda: FakeTransport({})
    used: list[str] = []
    _stub_generation(monkeypatch, used)
    body = {"topic": "PAP", "type": "sba", "exam_target": "frcr"}
    _material_stub(monkeypatch, _material())
    response = client.post("/v1/questions/generate", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["basis"] == "claims" and response.json()["graph_neighbours"] == 2
    _material_stub(monkeypatch, None)
    assert client.post("/v1/questions/generate", json=body).json()["basis"] == "chunks"
    assert used == ["claims", "chunks"]


def test_generate_route_refuses_claims_it_cannot_use(
    client: TestClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    app.dependency_overrides[api.get_transport] = lambda: FakeTransport({})
    _stub_generation(monkeypatch, [])
    _material_stub(monkeypatch, None)
    body = {"topic": "PAP", "type": "sba", "exam_target": "frcr", "basis": "claims"}
    assert client.post("/v1/questions/generate", json=body).status_code == 422
    seq = {**body, "type": "seq"}
    assert client.post("/v1/questions/generate", json=seq).status_code == 422
    chunks_only = {**body, "basis": "chunks"}
    assert client.post("/v1/questions/generate", json=chunks_only).json()["basis"] == "chunks"
