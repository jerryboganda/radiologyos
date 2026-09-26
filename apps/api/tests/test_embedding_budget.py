"""Embedding cost controls (ADR 0019): clients, batching, budget, admin view."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from apps.api.app.api import admin_usage
from apps.api.app.main import app, settings
from apps.worker.app.ingest.budget_alerts import alert_payload
from apps.worker.app.ingest.bulk import REPROCESS_SQL
from apps.worker.app.ingest.embedding import figure_text
from fastapi.testclient import TestClient
from packages.models.budget import (
    BudgetState,
    EmbeddingBudgetExhausted,
    billed_estimate_usd,
    crossed,
    list_price_usd,
)
from packages.models.embeddings import (
    MAX_BATCH_TEXTS,
    EmbeddingError,
    LocalEmbedder,
    VoyageEmbedder,
    content_hash,
    embed_text,
    estimate_tokens,
    plan_batches,
)
from packages.models.routing import EmbeddingBudget, EmbeddingConfig, EmbeddingTarget
from pydantic import ValidationError

BUDGET = EmbeddingBudget(hard_cap_tokens=195_000_000, warn_tokens=150_000_000)
VOYAGE = EmbeddingTarget(backend="voyage", model="voyage-4-large", api_key_env="TEST_VOYAGE")
LOCAL = EmbeddingTarget(backend="local", model="voyage-4-nano", base_url="http://embedder:8080")


def test_embed_text_collapses_space_and_does_not_repeat_the_heading() -> None:
    assert embed_text("Chest", "Chest\n\n\nPneumothorax   signs") == "Chest\nPneumothorax signs"
    assert embed_text("Chest", "Pneumothorax") == "Chest\nPneumothorax"
    assert embed_text("", "  a \t b ") == "a b"
    assert len(embed_text("", "x" * 20_000)) == 16_000
    assert content_hash("same") == content_hash("same") != content_hash("other")


def test_batches_respect_token_and_count_limits() -> None:
    big = "x" * 140_000  # ~46.7K estimated tokens each: two fit under 100K
    assert plan_batches([big, big, big]) == [[0, 1], [2]]
    small = ["tiny"] * (MAX_BATCH_TEXTS + 5)
    batches = plan_batches(small)
    assert [len(b) for b in batches] == [MAX_BATCH_TEXTS, 5]
    assert plan_batches([]) == []
    assert estimate_tokens("abc") == 2


def _voyage(handler: Any, sleeps: list[float]) -> VoyageEmbedder:
    return VoyageEmbedder(VOYAGE, 4, transport=httpx.MockTransport(handler), sleep=sleeps.append)


def _ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [{"index": i, "embedding": [0.5] * 4} for i in range(len(body["input"]))]
    return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 42}})


def test_voyage_batch_reports_real_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_VOYAGE", "key")
    result = _voyage(_ok, []).embed_batch(["a", "b"], "document")
    assert result.tokens == 42 and len(result.vectors) == 2


def test_voyage_retries_rate_limits_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_VOYAGE", "key")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"retry-after": "7"})
        return _ok(request)

    sleeps: list[float] = []
    assert _voyage(handler, sleeps).embed_batch(["a"], "document").tokens == 42
    assert sleeps == [7.0, 7.0]


def test_voyage_fails_fast_on_client_errors_and_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_VOYAGE", "key")
    with pytest.raises(EmbeddingError, match="HTTP 400"):
        _voyage(lambda r: httpx.Response(400), []).embed_batch(["a"], "document")
    sleeps: list[float] = []
    with pytest.raises(EmbeddingError, match="retries"):
        _voyage(lambda r: httpx.Response(503), sleeps).embed_batch(["a"], "document")
    assert len(sleeps) == 6
    monkeypatch.delenv("TEST_VOYAGE")
    with pytest.raises(EmbeddingError, match="not configured"):
        _voyage(_ok, []).embed_batch(["a"], "document")


def test_local_embedder_returns_vectors_or_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input_type"] == "query"
        return httpx.Response(200, json={"embeddings": [[0.1] * 4 for _ in body["texts"]]})

    good = LocalEmbedder(LOCAL, 4, transport=httpx.MockTransport(handler))
    assert good.embed(["q"], "query") == [[0.1] * 4]
    down = LocalEmbedder(LOCAL, 4, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert down.embed(["q"], "query") is None
    wrong_dims = LocalEmbedder(LOCAL, 8, transport=httpx.MockTransport(handler))
    assert wrong_dims.embed(["q"], "query") is None
    assert LocalEmbedder(VOYAGE, 4).embed(["q"], "query") is None  # never the paid API


def test_budget_levels_block_at_the_cap_and_report_crossings() -> None:
    assert BudgetState(10, BUDGET).level == "ok"
    assert BudgetState(150_000_000, BUDGET).level == "amber"
    assert BudgetState(195_000_000, BUDGET).level == "red"
    BudgetState(194_000_000, BUDGET).check(1_000_000)
    with pytest.raises(EmbeddingBudgetExhausted):
        BudgetState(194_000_000, BUDGET).check(1_000_001)
    assert crossed(149_999_999, 150_000_000, BUDGET) == ["amber"]
    assert crossed(140_000_000, 196_000_000, BUDGET) == ["amber", "red"]
    assert crossed(151_000_000, 152_000_000, BUDGET) == []
    assert BudgetState(3_000_000, BUDGET).free_tier_remaining == 197_000_000


def test_prices_and_billed_estimate_stay_zero_inside_the_free_tier() -> None:
    assert list_price_usd(3_300_000, "voyage-4-large") == pytest.approx(0.396)
    assert billed_estimate_usd(195_000_000, "voyage-4-large") == 0.0
    assert billed_estimate_usd(210_000_000, "voyage-4-large") == pytest.approx(1.2)


def test_config_rules() -> None:
    with pytest.raises(ValidationError):
        EmbeddingBudget(hard_cap_tokens=100, warn_tokens=100)
    with pytest.raises(ValidationError):
        EmbeddingBudget(hard_cap_tokens=250_000_000, warn_tokens=1)
    paid = EmbeddingConfig(dimensions=1024, document=VOYAGE, query=VOYAGE, budget=BUDGET)
    assert paid.query.model == "voyage-4-large"  # owner override: best model everywhere


def test_alert_payloads_carry_numbers_only() -> None:
    red = alert_payload("red", 195_000_000, BUDGET)
    assert "195.0M of the 195M" in red["body"] and red["url"] == "/settings"
    assert "150.0M" in alert_payload("amber", 150_000_000, BUDGET)["body"]


def test_figure_text_combines_description_fields() -> None:
    row = {"caption": "Fig 2", "modality": "CT", "anatomy": "chest",
           "description": "Bat-wing opacity", "findings": ["perihilar airspace disease"]}
    assert figure_text(row) == "Fig 2\nCT\nchest\nBat-wing opacity\nperihilar airspace disease"


def test_reprocess_only_selects_jobs_with_remaining_work() -> None:
    sql = " ".join(REPROCESS_SQL.split())
    assert "j.status <> 'succeeded'" in sql
    assert "vision_status = 'pending'" in sql and "c.embedding IS NULL" in sql


class _Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one(self) -> Any:
        return self.value

    def mappings(self) -> list[dict[str, Any]]:
        return self.value if isinstance(self.value, list) else []


class _Session:
    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        if "embedding_tokens_total" in sql:
            return _Result(3_300_000)
        if "voyage_model_tokens_total" in sql:
            assert params == {"m": "rerank-2.5"}  # the rerank cap counts rerank tokens only
            return _Result(151_000_000)
        if "ops_alerts" in sql and params == {"k": "rerank_budget"}:
            return _Result([{"id": "70000000-0000-0000-0000-000000000001", "level": "amber",
                             "created_at": "2026-09-26T00:00:00Z", "acknowledged_at": None}])
        return _Result([])


async def _fake_session() -> AsyncIterator[_Session]:
    yield _Session()


def _headers(role: str) -> dict[str, str]:
    return {"x-user-id": "10000000-0000-0000-0000-00000000000a",
            "x-tenant-id": "40000000-0000-0000-0000-000000000001", "x-role": role}


def test_admin_usage_is_admin_only_and_reports_zero_bill() -> None:
    settings.app_env = "test"
    app.dependency_overrides[admin_usage.tenant_db_session] = _fake_session
    try:
        client = TestClient(app)
        assert client.get("/v1/admin/embedding-usage").status_code == 401
        denied = client.get("/v1/admin/embedding-usage", headers=_headers("student"))
        assert denied.status_code == 403
        body = client.get("/v1/admin/embedding-usage", headers=_headers("org_admin")).json()
        assert body["status"] == "ok" and body["billed_estimate_usd"] == 0.0
        assert body["document_model"] == "voyage-4-large"
        assert body["query_model"] == "voyage-4-large"
        assert body["tokens_used"] == 3_300_000
        assert body["alerts"] == []  # the rerank alert is not an embedding alert
        rerank = body["rerank"]
        assert rerank["model"] == "rerank-2.5" and rerank["tokens_used"] == 151_000_000
        assert rerank["status"] == "amber" and rerank["billed_estimate_usd"] == 0.0
        assert rerank["hard_cap_tokens"] == 195_000_000
        assert [a["level"] for a in rerank["alerts"]] == ["amber"]
    finally:
        app.dependency_overrides.clear()
        settings.app_env = "dev"
