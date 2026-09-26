"""Query-time Voyage calls are metered against the 195M cap (ADR 0019 override)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.library import metered_embedding as metered
from packages.models.embeddings import BatchResult, VoyageEmbedder

TENANT = UUID("40000000-0000-0000-0000-000000000001")


class _Result:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _Session:
    def __init__(self, total: int) -> None:
        self.total = total

    async def execute(self, *_: Any) -> _Result:
        return _Result(self.total)

    async def commit(self) -> None:
        return None


def _wire(monkeypatch: pytest.MonkeyPatch, total: int) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"calls": [], "usage": [], "alerts": []}

    @asynccontextmanager
    async def fake_session(_tenant: UUID) -> AsyncIterator[_Session]:
        yield _Session(total)

    async def fake_usage(_s: Any, _t: UUID, model: str, tokens: int) -> None:
        seen["usage"].append((model, tokens))

    async def fake_alert(_e: Any, _t: UUID, level: str, used: int, _b: Any) -> bool:
        seen["alerts"].append((level, used))
        return True

    def fake_batch(self: VoyageEmbedder, texts: list[str], input_type: str) -> BatchResult:
        seen["calls"].append((self.model, input_type, len(texts)))
        return BatchResult([[0.1] * 1024 for _ in texts], 7)

    monkeypatch.setenv("VOYAGE_API_KEY", "test")
    monkeypatch.setattr(metered, "tenant_session", fake_session)
    monkeypatch.setattr(metered, "add_usage", fake_usage)
    monkeypatch.setattr(metered, "record_alert", fake_alert)
    monkeypatch.setattr(VoyageEmbedder, "embed_batch", fake_batch)
    return seen


async def test_queries_use_the_best_model_and_are_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, total=1_000)
    vectors = await metered.embed_metered(TENANT, ["pneumothorax"], "query")
    assert vectors is not None and len(vectors[0]) == 1024
    assert seen["calls"] == [("voyage-4-large", "query", 1)]
    assert seen["usage"] == [("voyage-4-large", 7)]
    assert seen["alerts"] == []


async def test_nothing_is_sent_past_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, total=195_000_000)
    assert await metered.embed_metered(TENANT, ["pneumothorax"], "query") is None
    assert seen["calls"] == [] and seen["usage"] == []
    assert seen["alerts"] == [("red", 195_000_000)]


async def test_crossing_the_warning_line_raises_amber(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, total=149_999_995)
    assert await metered.embed_metered(TENANT, ["q"], "query") is not None
    assert seen["alerts"] == [("amber", 150_000_002)]
