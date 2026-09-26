"""Figure card actions: "similar figures" and "quiz me on this figure" (ADR 0025)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import assessment
from apps.api.app.api import library as library_api
from apps.api.app.assessment import retrieval
from apps.api.app.assessment.contracts import GenerateRequest
from apps.api.app.library import search
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from fastapi.testclient import TestClient

USER, TENANT, FIGURE, SOURCE = uuid4(), uuid4(), uuid4(), uuid4()
ROW = {"id": uuid4(), "source_id": SOURCE, "source_title": "Synthetic deck", "page_no": 3,
       "figure_no": 0, "caption": "Fig 2", "description": "Axial CT with crazy paving.",
       "modality": "CT", "anatomy": "chest", "image_key": "k", "score": 0.9}
FIG = {"id": FIGURE, "source_id": SOURCE, "source_title": "Synthetic deck", "page_no": 3,
       "caption": "", "description": "Axial HRCT with crazy paving.", "modality": "CT",
       "anatomy": "chest", "findings": [], "bbox": [0, 0, 1, 1]}


class FakeSession:
    async def commit(self) -> None:
        return None


class UpTransport:
    def available(self) -> bool:
        return True


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def session() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    for module in (library_api, assessment):
        app.dependency_overrides[module.principal_context] = lambda: Principal(
            user_id=USER, tenant_id=TENANT)
        app.dependency_overrides[module.tenant_db_session] = session
    app.dependency_overrides[assessment.get_transport] = UpTransport
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_similar_figures_are_the_callers_own(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def similar(_s: Any, user: UUID, figure: UUID, limit: int) -> Any:
        seen.update(user=user, figure=figure, limit=limit)
        return [ROW] if figure == FIGURE else None

    monkeypatch.setattr(search, "similar_figures", similar)
    body = client.get(f"/v1/library/figures/{FIGURE}/similar?limit=5").json()
    assert seen == {"user": USER, "figure": FIGURE, "limit": 5}
    assert body[0]["figure_id"] == str(ROW["id"]) and body[0]["page_no"] == 3
    assert body[0]["image_path"] == f"/v1/library/figures/{ROW['id']}/image"
    assert client.get(f"/v1/library/figures/{uuid4()}/similar").status_code == 404
    assert client.get(f"/v1/library/figures/{FIGURE}/similar?limit=99").status_code == 422


def test_similar_figures_require_authentication() -> None:
    assert TestClient(app).get(f"/v1/library/figures/{FIGURE}/similar").status_code == 401


def test_figure_id_alone_is_a_valid_generation_scope() -> None:
    body = {"type": "sba", "exam_target": "frcr", "count": 1}
    assert GenerateRequest.model_validate({**body, "figure_id": str(FIGURE)}).figure_id == FIGURE
    with pytest.raises(ValueError):
        GenerateRequest.model_validate(body)


def _patch(monkeypatch: pytest.MonkeyPatch, figure: dict[str, Any] | None) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def exact(_s: Any, user: UUID, figure_id: UUID) -> Any:
        return figure if figure_id == FIGURE and user == USER else None

    async def gather(_s: Any, user: UUID, topic: Any, source_ids: Any, vector: Any,
                     with_figure: bool, figure: Any = None) -> list[Any]:
        seen.update(topic=topic, with_figure=with_figure, figure=figure)
        return []

    async def no_vector(_t: Any, query: str) -> None:
        seen["vector_query"] = query

    monkeypatch.setattr(retrieval, "exact_figure", exact)
    monkeypatch.setattr(retrieval, "gather_excerpts", gather)
    monkeypatch.setattr(assessment, "query_vector", no_vector)
    return seen


def test_quiz_on_a_figure_uses_it_as_f1_and_its_description_as_topic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _patch(monkeypatch, FIG)
    body = {"type": "sba", "exam_target": "fcps2_theory", "count": 1, "figure_id": str(FIGURE)}
    response = client.post("/v1/questions/generate", json=body)
    assert response.status_code == 422  # the fake library has no text excerpts
    assert seen["figure"] == FIG and seen["topic"] == "CT chest Axial HRCT with crazy paving."
    assert seen["vector_query"] == seen["topic"]


def test_quiz_on_a_missing_or_undescribed_figure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"type": "sba", "exam_target": "frcr", "count": 1}
    _patch(monkeypatch, FIG)
    missing = client.post("/v1/questions/generate", json={**body, "figure_id": str(uuid4())})
    assert missing.status_code == 404
    _patch(monkeypatch, {**FIG, "description": " "})
    bare = client.post("/v1/questions/generate", json={**body, "figure_id": str(FIGURE)})
    assert bare.status_code == 422 and bare.json()["detail"] == "figure is not described yet"


def test_figure_topic_prefers_the_caption() -> None:
    assert retrieval.figure_topic({**FIG, "caption": "  Crazy   paving "}) == "Crazy paving"
    assert retrieval.figure_topic({"caption": "", "description": ""}) == "radiology figure"
