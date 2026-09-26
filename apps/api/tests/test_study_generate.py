"""card_generate agent: prompt contract, citation guardrails, fake transport."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import study
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.app.study import generate
from apps.api.tests.study_fakes import MemoryStudyRepo
from fastapi.testclient import TestClient
from packages.library.parse_models import inline_schema
from packages.models.claude_code import ModelCall, ModelResult, UsageLimitError
from packages.models.gateway import build_call, load_agent, routing_config
from packages.study.card_models import CardBatch

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
USER = UUID("10000000-0000-4000-8000-000000000001")
TENANT = UUID("20000000-0000-4000-8000-000000000001")
TEXT = "Crazy paving on HRCT: ground-glass opacity with smooth septal thickening."


class FakeTransport:
    def __init__(self, output: dict[str, Any] | None = None, error: Exception | None = None):
        self.output = output or {"cards": []}
        self.error = error
        self.calls: list[ModelCall] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return ModelResult(output=self.output, duration_ms=1, cost_usd=0.0)


def _card(chunk_id: UUID, **overrides: Any) -> dict[str, Any]:
    return {"chunk_id": str(chunk_id), "curriculum_code": "CHEST", "topic": "PAP",
            "front": "HRCT sign of PAP?", "back": "Crazy paving.",
            "evidence": "Crazy paving on  HRCT", **overrides}


@pytest.fixture
def repo() -> Iterator[MemoryStudyRepo]:
    memory = MemoryStudyRepo()
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.principal_context] = lambda: Principal(USER, TENANT)
    app.dependency_overrides[study.get_now] = lambda: NOW
    yield memory
    app.dependency_overrides.clear()


def _use(transport: FakeTransport) -> TestClient:
    app.dependency_overrides[study.get_transport] = lambda: transport
    return TestClient(app)


def test_agent_is_versioned_on_the_extract_route_with_high_effort() -> None:
    agent = load_agent("card_generate")
    assert agent.prompt.route == "extract" and agent.prompt.effort == "high"
    assert agent.prompt.fixture == "evals/fixtures/study_v1.json"
    assert agent.schema == inline_schema(CardBatch)
    call = build_call(agent, "prompt")
    assert call.model == routing_config().routes[agent.prompt.route].targets[0].model
    assert call.effort == "high" and call.tools == ()


def test_prompt_carries_only_supplied_chunks_and_codes() -> None:
    chunk = {"id": uuid4(), "heading": "PAP", "page_from": 2, "page_to": 3, "text": "x" * 9000}
    prompt = generate.build_prompt([chunk], ["CHEST", "GI"], 4)
    assert str(chunk["id"]) in prompt and '"pages": "2-3"' in prompt
    assert '"max_cards": 4' in prompt and "x" * generate.CHUNK_CHARS in prompt
    assert "x" * (generate.CHUNK_CHARS + 1) not in prompt


def test_guardrails_reject_foreign_chunks_codes_and_unsupported_evidence() -> None:
    good, other = uuid4(), uuid4()
    chunks = {good: {"id": good, "text": TEXT}}
    batch = CardBatch.model_validate({"cards": [
        _card(good), _card(other), _card(good, curriculum_code="NOPE"),
        _card(good, evidence="Tree-in-bud nodules"), _card(good, front="Second?"),
    ]})
    kept, rejected = generate.accept_cards(batch, chunks, frozenset({"CHEST"}), 1)
    assert [c.front for c in kept] == ["HRCT sign of PAP?"] and rejected == 4


def test_generate_endpoint_creates_cited_cards(repo: MemoryStudyRepo) -> None:
    chunk = repo.add_chunk(USER, text=TEXT)
    foreign = uuid4()
    transport = FakeTransport({"cards": [_card(chunk), _card(foreign)]})
    response = _use(transport).post("/v1/study/cards/generate",
                                    json={"chunk_ids": [str(chunk)], "max_cards": 3})
    assert response.status_code == 201
    body = response.json()
    assert body["rejected"] == 1 and body["chunks_used"] == 1
    assert body["created"][0]["origin"] == "generated"
    assert body["created"][0]["citation"]["chunk_id"] == str(chunk)
    assert str(chunk) in transport.calls[0].user_prompt and TEXT in transport.calls[0].user_prompt


def test_generate_from_source_skips_carded_chunks(repo: MemoryStudyRepo) -> None:
    chunk = repo.add_chunk(USER, text=TEXT)
    source = repo.chunks[chunk][1]["source_id"]
    client = _use(FakeTransport({"cards": [_card(chunk)]}))
    first = client.post("/v1/study/cards/generate", json={"source_id": str(source)})
    assert first.status_code == 201 and len(first.json()["created"]) == 1
    again = client.post("/v1/study/cards/generate", json={"source_id": str(source)})
    assert again.status_code == 404


def test_generate_refuses_unowned_or_missing_input(repo: MemoryStudyRepo) -> None:
    client = _use(FakeTransport())
    assert client.post("/v1/study/cards/generate", json={}).status_code == 422
    other = repo.add_chunk(UUID(int=7))
    missing = client.post("/v1/study/cards/generate", json={"chunk_ids": [str(other)]})
    assert missing.status_code == 404


def test_model_failures_map_to_service_errors(repo: MemoryStudyRepo) -> None:
    chunk = str(repo.add_chunk(USER, text=TEXT))
    limited = _use(FakeTransport(error=UsageLimitError("limit")))
    assert limited.post("/v1/study/cards/generate",
                        json={"chunk_ids": [chunk]}).status_code == 503
    invalid = _use(FakeTransport({"cards": [{"front": "missing fields"}]}))
    assert invalid.post("/v1/study/cards/generate",
                        json={"chunk_ids": [chunk]}).status_code == 502
    assert repo.cards == {}
