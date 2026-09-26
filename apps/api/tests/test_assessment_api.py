"""Check gating, key hiding, and the assessment router (fake transport, no database)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import assessment as api
from apps.api.app.assessment import generation, store
from apps.api.app.assessment.contracts import public_question
from apps.api.app.main import app
from apps.api.tests.test_assessment_validation import EXCERPTS, sba_item, seq_item
from fastapi.testclient import TestClient
from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError
from packages.models.gateway import load_agent

TENANT = UUID("20000000-0000-0000-0000-000000000002")
USER = UUID("20000000-0000-0000-0000-0000000000aa")
PASS = {"single_best_answer": True, "key_supported": True, "no_cueing": True,
        "distractors_plausible": True, "difficulty_agrees": True, "verdict": "pass",
        "reasons": []}


class FakeTransport:
    """Answers each agent from a queue, matched by the agent's output schema."""

    def __init__(self, outputs: dict[str, list[Any]], up: bool = True) -> None:
        self.outputs = outputs
        self.up = up
        self.calls: list[str] = []

    def available(self) -> bool:
        return self.up

    def run(self, call: ModelCall) -> ModelResult:
        name = next(n for n in self.outputs if load_agent(n).schema == call.output_schema)
        self.calls.append(name)
        output = self.outputs[name].pop(0)
        if isinstance(output, Exception):
            raise output
        return ModelResult(output=output, duration_ms=1, cost_usd=0.0)


def _generated(*items: Any) -> dict[str, Any]:
    return {"items": [item.model_dump() for item in items]}


def test_only_checker_passed_items_become_active() -> None:
    fake = FakeTransport({
        "question_generate": [_generated(sba_item(), sba_item(topic="B"), sba_item(key_index=-1))],
        "question_check": [PASS, {**PASS, "verdict": "fail", "no_cueing": False,
                                  "reasons": ["no_cueing: length cue"]}],
    })
    outcome = generation.generate_items(fake, EXCERPTS, "sba", "fcps2_theory", 3, None)
    # Checks run in parallel and the fake hands out verdicts in call order, so
    # which item gets which verdict is scheduling-dependent; the gate is not.
    assert sorted(row["status"] for row in outcome.items) == ["active", "draft"]
    assert outcome.rejected == [{"index": 2, "reasons": ["sba_key_out_of_range"]}]
    assert fake.calls.count("question_check") == 2
    active = next(row for row in outcome.items if row["status"] == "active")
    assert active["exam_tags"] == ["fcps2_theory"] and active["answer"] == {"key": 0}
    assert active["citations"] and active["quality"]["passed"] is True


def test_uncited_generation_is_rejected_before_checking() -> None:
    fake = FakeTransport({"question_generate": [_generated(sba_item(citations=["E99"]))],
                          "question_check": []})
    outcome = generation.generate_items(fake, EXCERPTS, "sba", "frcr", 1, None)
    assert outcome.items == [] and "citation_not_supplied" in outcome.rejected[0]["reasons"]
    assert "question_check" not in fake.calls


def test_checker_error_keeps_draft_and_usage_limit_propagates() -> None:
    fake = FakeTransport({"question_generate": [_generated(seq_item())],
                          "question_check": [ModelCallError("boom")]})
    outcome = generation.generate_items(fake, EXCERPTS, "seq", "imm", 1, None)
    assert outcome.items[0]["status"] == "draft"
    limited = FakeTransport({"question_generate": [_generated(seq_item())],
                             "question_check": [UsageLimitError("limit")]})
    with pytest.raises(UsageLimitError):
        generation.generate_items(limited, EXCERPTS, "seq", "imm", 1, None)


def _row(item_type: str = "sba") -> dict[str, Any]:
    item = sba_item() if item_type == "sba" else seq_item(item_type)
    parts = generation.to_row(item, None, EXCERPTS, "fcps2_theory")
    return {**parts, "id": uuid4(), "created_at": datetime.now(UTC)}


def test_public_view_never_carries_keys_or_explanations() -> None:
    for item_type in ("sba", "seq"):
        view = public_question(_row(item_type)).model_dump(mode="json")
        flat = str(view)
        assert "answer" not in view and "explanation" not in view and "citations" not in view
        assert "because" not in flat and "marking" not in flat and "key" not in view


class FakeSession:
    async def commit(self) -> None:
        return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def session() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    def principal() -> api.Principal:
        return api.Principal(user_id=USER, tenant_id=TENANT)

    app.dependency_overrides[api.principal_context] = principal
    app.dependency_overrides[api.tenant_db_session] = session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_generate_returns_503_when_model_runtime_missing(client: TestClient) -> None:
    app.dependency_overrides[api.get_transport] = lambda: FakeTransport({}, up=False)
    body = {"topic": "crazy paving", "type": "sba", "exam_target": "fcps2_theory"}
    assert client.post("/v1/questions/generate", json=body).status_code == 503
    assert client.post("/v1/questions/generate",
                       json={"type": "sba", "exam_target": "frcr"}).status_code == 422


def test_attempt_is_refused_while_question_is_in_an_open_exam(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row()

    async def get_question(*_: Any) -> dict[str, Any]:
        return row

    async def in_open_exam(*_: Any) -> bool:
        return True

    monkeypatch.setattr(store, "get_question", get_question)
    monkeypatch.setattr(store, "in_open_exam", in_open_exam)
    response = client.post(f"/v1/questions/{row['id']}/attempt", json={"selected_option": 0})
    assert response.status_code == 409
    assert "key" not in response.json()


def test_sba_attempt_reveals_key_with_citations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row()
    saved: list[dict[str, Any]] = []

    async def get_question(*_: Any) -> dict[str, Any]:
        return row

    async def in_open_exam(*_: Any) -> bool:
        return False

    async def insert_attempt(_s: Any, _t: Any, _u: Any, values: dict[str, Any]) -> UUID:
        saved.append(values)
        return uuid4()

    monkeypatch.setattr(store, "get_question", get_question)
    monkeypatch.setattr(store, "in_open_exam", in_open_exam)
    monkeypatch.setattr(store, "insert_attempt", insert_attempt)
    body = client.post(f"/v1/questions/{row['id']}/attempt", json={"selected_option": 1}).json()
    assert (body["correct"], body["key"], body["score"]) == (False, 0, 0.0)
    assert body["citations"] and all(o["citations"] for o in body["option_explanations"])
    assert saved[0]["graded_by"] == "rule:sba_exact"
    bad = client.post(f"/v1/questions/{row['id']}/attempt", json={"selected_option": 7})
    assert bad.status_code == 422


def test_exam_list_route_is_mounted_and_requires_identity() -> None:
    from apps.api.app.main import app

    assert "get" in app.openapi()["paths"]["/v1/exams"]
    assert TestClient(app).get("/v1/exams").status_code == 401
