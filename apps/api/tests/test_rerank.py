"""Voyage reranker (ADR 0028): client, per-model budget, fail-open, search ordering."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from apps.api.app.library import rerank as metered
from apps.api.app.library import search
from apps.worker.app.ingest.budget_alerts import alert_payload
from packages.models.gateway import routing_config
from packages.models.rerank import (
    MAX_DOCUMENT_CHARS,
    RerankError,
    RerankResult,
    VoyageReranker,
    estimate_tokens,
)
from packages.models.routing import (
    EmbeddingBudget,
    ModelRoutingConfig,
    RerankConfig,
    RouteName,
    require_mock_routes,
)
from pydantic import ValidationError

TENANT = UUID("40000000-0000-0000-0000-000000000001")
BUDGET = EmbeddingBudget(hard_cap_tokens=195_000_000, warn_tokens=150_000_000)
CONFIG = RerankConfig(backend="voyage", model="rerank-2.5", api_key_env="TEST_RERANK_KEY",
                      base_url="https://voyage.test/v1", top_k=8, candidates=24,
                      min_score=0.2, budget=BUDGET)


def _reranker(handler: Any, monkeypatch: pytest.MonkeyPatch) -> VoyageReranker:
    monkeypatch.setenv("TEST_RERANK_KEY", "secret-test-key")
    return VoyageReranker(CONFIG, transport=httpx.MockTransport(handler), sleep=lambda _s: None)


def test_client_sends_the_documented_shape_and_parses_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"object": "list", "model": "rerank-2.5",
                                         "data": [{"index": 1, "relevance_score": 0.91},
                                                  {"index": 0, "relevance_score": 0.12}],
                                         "usage": {"total_tokens": 42}})

    result = _reranker(handler, monkeypatch).rerank("q", ["a" * 9000, "b"], top_k=5)
    assert seen["url"] == "https://voyage.test/v1/rerank"
    assert seen["auth"] == "Bearer secret-test-key"
    body = seen["body"]
    assert body["model"] == "rerank-2.5" and body["query"] == "q" and body["truncation"]
    assert body["top_k"] == 2  # never more than the documents sent
    assert len(body["documents"][0]) == MAX_DOCUMENT_CHARS
    assert [(r.index, r.score) for r in result.ranking] == [(1, 0.91), (0, 0.12)]
    assert result.tokens == 42


def test_client_retries_rate_limits_then_fails_fast_on_client_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter([429, 200])

    def flaky(_r: httpx.Request) -> httpx.Response:
        code = next(statuses)
        return httpx.Response(code, json={"data": [{"index": 0, "relevance_score": 0.5}],
                                          "usage": {"total_tokens": 3}})

    assert _reranker(flaky, monkeypatch).rerank("q", ["a", "b"], 2).tokens == 3
    calls: list[int] = []

    def denied(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"detail": "bad key"})

    with pytest.raises(RerankError, match="HTTP 401") as err:
        _reranker(denied, monkeypatch).rerank("secret query", ["secret doc"], 1)
    assert calls == [1] and "secret" not in str(err.value)


@pytest.mark.parametrize("payload", [
    {"data": [{"index": 5, "relevance_score": 0.5}]},
    {"data": [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.4}]},
    {"data": [{"idx": 0}]},
    {"nothing": []},
])
def test_client_rejects_malformed_responses(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    reranker = _reranker(lambda _r: httpx.Response(200, json=payload), monkeypatch)
    with pytest.raises(RerankError):
        reranker.rerank("q", ["a", "b"], 2)


def test_token_estimate_counts_the_query_once_per_document() -> None:
    assert estimate_tokens("q" * 30, ["d" * 300] * 4) == 11 * 4 + 101 * 4


def test_config_rules_and_checked_in_block() -> None:
    with pytest.raises(ValidationError):
        RerankConfig(backend="voyage", model="m", top_k=30, candidates=10, min_score=0.1,
                     budget=BUDGET)
    with pytest.raises(ValidationError):
        RerankConfig(backend="voyage", model="m", top_k=5, candidates=10, min_score=1.5,
                     budget=BUDGET)
    cfg = routing_config().rerank
    assert cfg is not None and cfg.model == "rerank-2.5"
    assert cfg.api_key_env == "VOYAGE_API_KEY" and cfg.top_k <= cfg.candidates
    assert cfg.budget.hard_cap_tokens == 195_000_000 and cfg.budget.warn_tokens == 150_000_000
    mock = {"targets": [{"backend": "mock", "model": "mock-only"}]}
    preview = ModelRoutingConfig.model_validate({
        "config_version": "t", "provider_gate": {"status": "blocked"},
        "default_backend": "mock", "routes": {r.value: mock for r in RouteName}})
    require_mock_routes(preview)
    with pytest.raises(ValueError, match="reranker"):
        require_mock_routes(preview.model_copy(update={"rerank": CONFIG}))


def test_rerank_alert_payload_is_numbers_only_and_distinct() -> None:
    red = alert_payload("red", 195_000_001, BUDGET, "rerank_budget")
    assert red["tag"] == "rerank-budget" and "rerank" in red["title"]
    assert "fused order" in red["body"]
    assert alert_payload("red", 1, BUDGET)["tag"] == "embedding-budget"


# --- metered, fail-open reranking -------------------------------------------------

HITS = [{"id": uuid4(), "heading": "H", "text": f"chunk {i}", "score": 0.1} for i in range(4)]


class _Result:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _Session:
    def __init__(self, total: int, seen: dict[str, list[Any]]) -> None:
        self.total, self.seen = total, seen

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        self.seen["sql"].append((str(statement), params))
        return _Result(self.total)

    async def commit(self) -> None:
        return None


def _wire(monkeypatch: pytest.MonkeyPatch, total: int,
          result: RerankResult | Exception | None = None) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"calls": [], "usage": [], "alerts": [], "sql": []}

    @asynccontextmanager
    async def fake_session(_tenant: UUID) -> AsyncIterator[_Session]:
        yield _Session(total, seen)

    async def fake_usage(_s: Any, _t: UUID, model: str, tokens: int) -> None:
        seen["usage"].append((model, tokens))

    async def fake_alert(_e: Any, _t: UUID, level: str, used: int, _b: Any, kind: str) -> bool:
        seen["alerts"].append((kind, level, used))
        return True

    def fake_rerank(self: VoyageReranker, query: str, docs: list[str], top_k: int) -> Any:
        seen["calls"].append((self.model, len(docs), top_k))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setenv("VOYAGE_API_KEY", "test")
    monkeypatch.setattr(metered, "tenant_session", fake_session)
    monkeypatch.setattr(metered, "add_usage", fake_usage)
    monkeypatch.setattr(metered, "record_alert", fake_alert)
    monkeypatch.setattr(VoyageReranker, "rerank", fake_rerank)
    return seen


def _ranking(*pairs: tuple[int, float], tokens: int = 50) -> RerankResult:
    from packages.models.rerank import Ranked

    return RerankResult([Ranked(i, s) for i, s in pairs], tokens)


async def test_reranks_drops_low_scores_and_meters_its_own_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, 1_000, _ranking((2, 0.9), (0, 0.6), (3, 0.19), (1, 0.05)))
    out = await metered.rerank_hits(TENANT, "what is crazy paving", HITS, 3)
    assert out.reranked and [h["id"] for h in out.hits] == [HITS[2]["id"], HITS[0]["id"]]
    assert out.hits[0]["score"] == 0.9  # below min_score 0.2 is dropped
    assert seen["calls"] == [("rerank-2.5", 4, 3)]
    assert seen["usage"] == [("rerank-2.5", 50)]
    sql, params = seen["sql"][0]
    assert "voyage_model_tokens_total" in sql and params == {"m": "rerank-2.5"}
    assert all("embedding_tokens_total" not in s for s, _ in seen["sql"])


async def test_past_the_rerank_cap_nothing_is_sent_and_order_is_rrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, 195_000_000, _ranking((3, 0.9)))
    out = await metered.rerank_hits(TENANT, "q", HITS, 2)
    assert not out.reranked and out.hits == HITS[:2]
    assert seen["calls"] == [] and seen["usage"] == []
    assert seen["alerts"] == [("rerank_budget", "red", 195_000_000)]


async def test_crossing_the_rerank_warning_raises_amber(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, 149_999_990, _ranking((0, 0.9), tokens=20))
    assert (await metered.rerank_hits(TENANT, "q", HITS, 2)).reranked
    assert seen["alerts"] == [("rerank_budget", "amber", 150_000_010)]


async def test_provider_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, 0, RerankError("voyage rerank returned HTTP 503"))
    out = await metered.rerank_hits(TENANT, "q", HITS, 3)
    assert not out.reranked and out.hits == HITS[:3] and seen["usage"] == []


async def test_without_a_key_no_database_or_network_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, 0, _ranking((0, 0.9)))
    monkeypatch.delenv("VOYAGE_API_KEY")
    out = await metered.rerank_hits(TENANT, "q", HITS, 2)
    assert out == metered.Reranked(HITS[:2], False)
    assert seen["sql"] == [] and seen["calls"] == []
    assert metered.candidate_pool(8) == 8


async def test_ranked_search_pools_candidates_then_reranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, 0, _ranking((3, 0.8), (1, 0.7)))
    asked: list[int] = []

    async def fake_hybrid(_s: Any, _u: UUID, _q: str, _v: Any, limit: int) -> Any:
        asked.append(limit)
        return HITS

    monkeypatch.setattr(search, "hybrid_search", fake_hybrid)
    out = await metered.ranked_search(None, TENANT, uuid4(), "a or b", None, 2,  # type: ignore[arg-type]
                                      rerank_query="natural question")
    assert asked == [24]  # the candidate pool, not the page size
    assert [h["id"] for h in out.hits] == [HITS[3]["id"], HITS[1]["id"]] and out.reranked
    monkeypatch.delenv("VOYAGE_API_KEY")
    plain = await metered.ranked_search(None, TENANT, uuid4(), "q", None, 2)  # type: ignore[arg-type]
    assert asked[-1] == 2 and plain.hits == HITS[:2] and not plain.reranked
