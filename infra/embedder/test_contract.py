"""Contract tests for the local embedder with the model replaced by a fake.

No torch, sentence-transformers, or model download is needed. Run with
`python -m pytest -q infra/embedder`.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Load under a unique name: `app` would shadow or collide with other modules.
_SPEC = importlib.util.spec_from_file_location(
    "radbrain_embedder_app", Path(__file__).with_name("app.py")
)
assert _SPEC is not None and _SPEC.loader is not None
embedder = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = embedder
_SPEC.loader.exec_module(embedder)

SECRET = "patient-free-synthetic-marker-7f3a"


class FakeVectors:
    def __init__(self, rows: list[list[float]]) -> None:
        self._rows = rows

    def tolist(self) -> list[list[float]]:
        return self._rows


class FakeModel:
    def __init__(self, dimensions: int = 1024) -> None:
        self.dimensions = dimensions
        self.calls: list[tuple[str, list[str], dict[str, Any]]] = []

    def _encode(self, kind: str, inputs: list[str], **kwargs: Any) -> FakeVectors:
        self.calls.append((kind, list(inputs), kwargs))
        return FakeVectors([[float(i)] * self.dimensions for i in range(len(inputs))])

    def encode_query(self, inputs: list[str], **kwargs: Any) -> FakeVectors:
        return self._encode("query", inputs, **kwargs)

    def encode_document(self, inputs: list[str], **kwargs: Any) -> FakeVectors:
        return self._encode("document", inputs, **kwargs)


def _started(loader: Callable[[], Any]) -> tuple[Any, TestClient]:
    app = embedder.create_app(loader=loader)
    return app, TestClient(app)


@pytest.fixture
def fake() -> FakeModel:
    return FakeModel()


@pytest.fixture
def client(fake: FakeModel) -> Iterator[TestClient]:
    app, test_client = _started(lambda: fake)
    with test_client:
        app.state.loader_thread.join(timeout=5)
        yield test_client


def test_health_reports_the_contract_once_loaded(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "voyage-4-nano", "dimensions": 1024}


def test_query_embeddings_follow_input_order(client: TestClient, fake: FakeModel) -> None:
    response = client.post("/embed", json={"texts": ["a", "b", "c"], "input_type": "query"})

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "voyage-4-nano"
    assert body["dimensions"] == 1024
    assert [row[0] for row in body["embeddings"]] == [0.0, 1.0, 2.0]
    assert all(len(row) == 1024 for row in body["embeddings"])
    kind, texts, kwargs = fake.calls[0]
    assert (kind, texts) == ("query", ["a", "b", "c"])
    assert kwargs["truncate_dim"] == 1024
    assert kwargs["normalize_embeddings"] is True


def test_document_input_uses_the_document_prompt(client: TestClient, fake: FakeModel) -> None:
    response = client.post("/embed", json={"texts": ["doc"], "input_type": "document"})

    assert response.status_code == 200
    assert [call[0] for call in fake.calls] == ["document"]


def test_long_text_is_truncated_not_rejected(client: TestClient, fake: FakeModel) -> None:
    response = client.post("/embed", json={"texts": ["x" * 20_000, "y"], "input_type": "query"})

    assert response.status_code == 200
    _, texts, _ = fake.calls[0]
    assert [len(text) for text in texts] == [16_000, 1]


def test_sixty_four_texts_are_accepted(client: TestClient) -> None:
    response = client.post("/embed", json={"texts": ["t"] * 64, "input_type": "document"})

    assert response.status_code == 200
    assert len(response.json()["embeddings"]) == 64


@pytest.mark.parametrize(
    "payload",
    [
        {"texts": [], "input_type": "query"},
        {"texts": ["t"] * 65, "input_type": "query"},
        {"texts": [""], "input_type": "query"},
        {"texts": ["ok", 7], "input_type": "query"},
        {"texts": "not-a-list", "input_type": "query"},
        {"texts": ["ok"]},
        {"texts": ["ok"], "input_type": "passage"},
        {"input_type": "query"},
    ],
)
def test_invalid_requests_are_rejected(
    client: TestClient, fake: FakeModel, payload: dict[str, Any]
) -> None:
    response = client.post("/embed", json=payload)

    assert response.status_code == 422
    assert fake.calls == []


def test_malformed_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/embed", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422


def test_validation_errors_do_not_echo_input_text(client: TestClient) -> None:
    response = client.post("/embed", json={"texts": [SECRET] * 65, "input_type": "query"})

    assert response.status_code == 422
    assert SECRET not in response.text


def test_logs_never_contain_input_text(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        client.post("/embed", json={"texts": [SECRET], "input_type": "query"})
        client.post("/embed", json={"texts": [SECRET] * 65, "input_type": "query"})

    assert "embedded input_type=query count=1" in caplog.text
    assert SECRET not in caplog.text


def test_service_answers_503_until_the_model_loads(fake: FakeModel) -> None:
    release = threading.Event()

    def slow_loader() -> FakeModel:
        release.wait(timeout=5)
        return fake

    app, test_client = _started(slow_loader)
    with test_client:
        health = test_client.get("/health")
        embed = test_client.post("/embed", json={"texts": ["a"], "input_type": "query"})
        release.set()
        app.state.loader_thread.join(timeout=5)
        ready = test_client.get("/health")

    assert health.status_code == 503
    assert health.json()["status"] == "loading"
    assert embed.status_code == 503
    assert ready.status_code == 200


def test_failed_load_keeps_health_unavailable() -> None:
    def broken_loader() -> FakeModel:
        raise RuntimeError("weights missing")

    app, test_client = _started(broken_loader)
    with test_client:
        app.state.loader_thread.join(timeout=5)
        health = test_client.get("/health")

    assert health.status_code == 503
    assert health.json()["status"] == "error"


def test_wrong_dimension_output_is_an_error() -> None:
    app, test_client = _started(lambda: FakeModel(dimensions=2048))
    with test_client:
        app.state.loader_thread.join(timeout=5)
        response = test_client.post("/embed", json={"texts": ["a"], "input_type": "query"})

    assert response.status_code == 500
