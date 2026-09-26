"""Curriculum approval and blueprint routes: auth, roles, hash binding (no database)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.api import assessment as assessment_api
from apps.api.app.api import blueprints as blueprints_api
from apps.api.app.api import curriculum as curriculum_api
from apps.api.app.assessment import blueprints, exams
from apps.api.app.knowledge import curriculum_review
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from fastapi.testclient import TestClient
from packages.curriculum.loader import radiology_hash

TENANT = UUID("20000000-0000-0000-0000-000000000002")
USER = UUID("20000000-0000-0000-0000-0000000000aa")


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        self.statements.append((str(statement), params or {}))
        return FakeResult()

    async def commit(self) -> None:
        self.commits += 1


class FakeResult:
    def mappings(self) -> list[dict[str, Any]]:
        return []

    def __iter__(self) -> Iterator[Any]:
        return iter([])


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


def _client(session: FakeSession, role: str) -> TestClient:
    async def db() -> AsyncIterator[FakeSession]:
        yield session

    def principal() -> Principal:
        return Principal(user_id=USER, tenant_id=TENANT, role=role)

    for module in (curriculum_api, blueprints_api, assessment_api):
        app.dependency_overrides[module.principal_context] = principal
        app.dependency_overrides[module.tenant_db_session] = db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_routes_are_mounted_and_require_identity() -> None:
    paths = app.openapi()["paths"]
    for path in ("/v1/knowledge/curriculum", "/v1/knowledge/curriculum/decision",
                 "/v1/knowledge/curriculum/candidates", "/v1/knowledge/curriculum/reviews",
                 "/v1/blueprints", "/v1/blueprints/{blueprint_id}",
                 "/v1/blueprints/{blueprint_id}/overrides",
                 "/v1/blueprints/{blueprint_id}/approve"):
        assert path in paths, path
    anonymous = TestClient(app)
    assert anonymous.get("/v1/knowledge/curriculum").status_code == 401
    assert anonymous.post("/v1/knowledge/curriculum/decision", json={}).status_code == 401
    assert anonymous.get("/v1/blueprints").status_code == 401


def test_curriculum_tree_is_readable_and_pending_by_default(session: FakeSession) -> None:
    body = _client(session, "student").get(
        "/v1/knowledge/curriculum", params={"exam_target": "frcr"}).json()
    assert body["pack_status"] == "draft_pending_owner_approval"
    assert body["review_status"] == "pending" and body["content_hash"] == radiology_hash()
    codes = {s["code"] for s in body["systems"]}
    assert "CHEST" in codes and "PHYSICS" not in codes  # physics is not an FRCR 2 target
    chest = next(s for s in body["systems"] if s["code"] == "CHEST")
    assert any(t["code"] == "CHEST.PULM_VASC" and t["children"] for t in chest["children"])
    candidates = _client(session, "student").get(
        "/v1/knowledge/curriculum/candidates", params={"max_level": "topic"}).json()
    assert {c["level"] for c in candidates} == {"system", "topic"}


def test_students_cannot_approve_curriculum_or_blueprints(session: FakeSession) -> None:
    client = _client(session, "student")
    decision = {"decision": "approved", "content_hash": radiology_hash()}
    assert client.post("/v1/knowledge/curriculum/decision", json=decision).status_code == 403
    assert client.put("/v1/blueprints/frcr_2a/overrides",
                      json={"overrides": {}}).status_code == 403
    assert client.post("/v1/blueprints/frcr_2a/approve",
                       json={"content_hash": "a" * 64}).status_code == 403
    assert session.statements == []  # nothing was written


def test_owner_approval_is_hash_bound_and_audited(session: FakeSession) -> None:
    client = _client(session, "org_admin")
    stale = {"decision": "approved", "content_hash": "b" * 64}
    assert client.post("/v1/knowledge/curriculum/decision", json=stale).status_code == 409
    ok = client.post("/v1/knowledge/curriculum/decision",
                     json={"decision": "approved", "content_hash": radiology_hash(),
                           "notes": "Looks right"})
    assert ok.status_code == 200
    sql = " ".join(statement for statement, _ in session.statements)
    assert "INSERT INTO curriculum_reviews" in sql and "INSERT INTO audit_log" in sql
    assert session.commits == 1


def test_blueprint_views_overrides_and_approval(session: FakeSession) -> None:
    client = _client(session, "superadmin")
    listed = client.get("/v1/blueprints").json()
    assert len(listed) == len(blueprints.packaged()) and not any(b["approved"] for b in listed)
    one = client.get("/v1/blueprints/frcr_2a").json()
    assert one["items"] == {"sba": 120} and one["overrides"] == {}
    assert client.get("/v1/blueprints/nope").status_code == 404
    bad = client.put("/v1/blueprints/frcr_2a/overrides",
                     json={"overrides": {"exam_target": "imm"}})
    assert bad.status_code == 422
    good = client.put("/v1/blueprints/imm_theory/overrides",
                      json={"overrides": {"duration_minutes": 100}})
    assert good.status_code == 200
    stale = client.post("/v1/blueprints/frcr_2a/approve", json={"content_hash": "c" * 64})
    assert stale.status_code == 409
    approved = client.post("/v1/blueprints/frcr_2a/approve",
                           json={"content_hash": one["content_hash"]})
    assert approved.status_code == 200
    sql = " ".join(statement for statement, _ in session.statements)
    assert "INSERT INTO exam_blueprints" in sql and "INSERT INTO audit_log" in sql


def test_exam_creation_routes_blueprint_papers(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    async def create(_s: Any, _t: UUID, _u: UUID, config: dict[str, Any]) -> UUID:
        seen.append(config)
        if config["blueprint_id"] == "nope":
            raise blueprints.UnknownBlueprint("nope")
        raise exams.NotEnoughQuestions("empty bank")

    monkeypatch.setattr(exams, "create_exam", create)
    client = _client(session, "student")
    assert client.post("/v1/exams", json={"blueprint_id": "nope"}).status_code == 404
    response = client.post("/v1/exams", json={"blueprint_id": "frcr_2a", "blueprint_items": 10})
    assert response.status_code == 422 and seen[-1]["blueprint_items"] == 10
    assert client.post("/v1/exams", json={"mode": "exam"}).status_code == 422


def test_curriculum_status_uses_the_latest_decision_for_this_hash(
    monkeypatch: pytest.MonkeyPatch, session: FakeSession
) -> None:
    async def history(_s: Any, _n: int = 20) -> list[dict[str, Any]]:
        return [{"content_hash": "0" * 64, "decision": "approved", "decided_at": None,
                 "notes": ""},
                {"content_hash": radiology_hash(), "decision": "rejected", "decided_at": None,
                 "notes": "Add IR"}]

    monkeypatch.setattr(curriculum_review, "history", history)
    body = _client(session, "student").get("/v1/knowledge/curriculum").json()
    assert body["review_status"] == "rejected" and body["notes"] == "Add IR"
