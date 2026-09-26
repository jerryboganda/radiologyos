"""Knowledge agents load with route/effort/schema; fixtures; API routes; deferral."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from apps.api.app.main import app
from apps.worker.app.knowledge.runtime import Deferred, KnowledgeDeps, call_agent
from evals.contracts import load_eval_fixtures
from fastapi.testclient import TestClient
from packages.knowledge.models import KnowledgeExtraction, PaperTopics, TopicClassification
from packages.library.parse_models import inline_schema
from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError
from packages.models.gateway import build_call, load_agent, run_agent

ROOT = Path(__file__).resolve().parents[3]
AGENTS = {
    "knowledge_extract": ("extract", KnowledgeExtraction, ()),
    "topic_classify": ("classify", TopicClassification, ()),
    "paper_topics": ("classify", PaperTopics, ("Read",)),
}


class FakeTransport:
    def __init__(self, output: dict[str, Any] | Exception) -> None:
        self.output = output
        self.calls: list[ModelCall] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        if isinstance(self.output, Exception):
            raise self.output
        return ModelResult(output=self.output, duration_ms=1, cost_usd=0.0)


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_agent_uses_named_route_high_effort_and_generated_schema(name: str) -> None:
    route, model, tools = AGENTS[name]
    agent = load_agent(name)
    assert agent.prompt.route == route and agent.prompt.effort == "high"
    assert agent.output_model is model
    assert agent.schema == inline_schema(model)
    assert agent.prompt.fixture == "evals/fixtures/knowledge_v1.json"
    call = build_call(agent, "prompt")
    assert call.effort == "high" and call.tools == tools
    assert "untrusted" in agent.prompt.system_prompt


def test_fixture_is_synthetic_and_covers_every_knowledge_agent() -> None:
    fixture = load_eval_fixtures(ROOT / "evals" / "fixtures" / "knowledge_v1.json")
    assert fixture.data_class == "synthetic"
    covered = {case.prompt.split("/")[0] for case in fixture.cases}
    assert covered == set(AGENTS)
    for case in fixture.cases:
        assert (ROOT / "packages" / "prompts" / case.prompt).is_file()
        assert case.route.value == AGENTS[case.prompt.split("/")[0]][0]
    extract = next(c for c in fixture.cases if c.case_id == "extract-uip-verbatim-spans")
    span = extract.expected["negation_preserved"]
    assert isinstance(span, str) and span in str(extract.input["chunk_text"])


def test_run_agent_validates_knowledge_output() -> None:
    good = {"concepts": [], "claims": [], "relations": []}
    parsed, _ = run_agent(FakeTransport(good), "knowledge_extract", "p")
    assert isinstance(parsed, KnowledgeExtraction)
    bad = {"concepts": [], "claims": [{"concept": "x"}], "relations": []}
    with pytest.raises(ModelCallError, match="schema validation"):
        run_agent(FakeTransport(bad), "knowledge_extract", "p")


def test_call_agent_defers_on_usage_limit_and_skips_on_model_error() -> None:
    engine: Any = None
    limited = KnowledgeDeps(engine=engine, transport=FakeTransport(UsageLimitError("limit")))
    with pytest.raises(Deferred):
        call_agent(limited, "topic_classify", "p")
    broken = KnowledgeDeps(engine=engine, transport=FakeTransport(ModelCallError("x")))
    assert call_agent(broken, "topic_classify", "p") is None
    assert call_agent(KnowledgeDeps(engine=engine, transport=None), "topic_classify", "p") is None
    ok = KnowledgeDeps(engine=engine, transport=FakeTransport({"topics": []}))
    assert isinstance(call_agent(ok, "topic_classify", "p"), TopicClassification)


def test_knowledge_routes_are_mounted_and_require_identity() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/v1/knowledge/concepts", "/v1/knowledge/concepts/{concept_id}",
        "/v1/knowledge/conflicts", "/v1/knowledge/conflicts/{conflict_id}/resolve",
        "/v1/knowledge/topic-weights", "/v1/knowledge/topic-weights/approve",
        "/v1/knowledge/sources/{source_id}/extract",
    ):
        assert path in paths, path
    client = TestClient(app)
    assert client.get("/v1/knowledge/concepts").status_code == 401
    assert client.post("/v1/knowledge/topic-weights/approve",
                       json={"exam_target": "imm"}).status_code == 401


def test_celery_registers_the_knowledge_task() -> None:
    from apps.worker.app.celery_app import celery_app

    celery_app.loader.import_default_modules()
    assert "radbrain.knowledge_extract" in celery_app.tasks
