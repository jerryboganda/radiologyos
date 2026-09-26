"""Review queue, duplicate rejection, grading hand-off, and migration shape (no database)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import assessment as api
from apps.api.app.api import exams as exams_api
from apps.api.app.assessment import dedupe, exams, item_stats, retrieval, review, review_store
from apps.api.app.assessment import store as question_store
from apps.api.app.main import app
from apps.api.tests.test_assessment_api import (  # noqa: F401
    PASS,
    TENANT,
    FakeTransport,
    client,
)
from apps.api.tests.test_assessment_depth import NOW, stored
from apps.api.tests.test_assessment_validation import EXCERPTS, sba_item
from fastapi.testclient import TestClient
from packages.assessment.duplicates import DuplicateHit

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
             / "20260926_0011_assessment_depth.py")


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    actions: list[str] = []

    async def audit(_s: Any, _p: Any, action: str, *_: Any) -> None:
        actions.append(action)

    async def save_review(*_: Any) -> None:
        return None

    monkeypatch.setattr(review, "audit", audit)
    monkeypatch.setattr(review_store, "save_review", save_review)
    yield actions


def _serve(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any], valid: bool = True,
           open_exam: bool = False) -> None:
    async def get_for_review(*_: Any) -> dict[str, Any]:
        return row

    async def citations_valid(*_: Any) -> bool:
        return valid

    async def in_open_exam(*_: Any) -> bool:
        return open_exam

    monkeypatch.setattr(review_store, "get_for_review", get_for_review)
    monkeypatch.setattr(review_store, "citations_valid", citations_valid)
    monkeypatch.setattr(question_store, "in_open_exam", in_open_exam)


def test_review_queue_shows_drafts_with_keys_and_checker_reasons(
    client: TestClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    row = {**stored(), "status": "draft",
           "quality": {"passed": False, "check": {"reasons": ["no_cueing: length cue"]}}}

    async def list_drafts(*_: Any) -> list[dict[str, Any]]:
        return [row]

    monkeypatch.setattr(review_store, "list_drafts", list_drafts)
    body = client.get("/v1/questions/review").json()
    assert body[0]["checker_reasons"] == ["no_cueing: length cue"]
    assert body[0]["key"] == 0 and body[0]["citations"]


def test_approve_activates_only_with_valid_citations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, audited: list[str]  # noqa: F811
) -> None:
    row = {**stored(), "status": "draft"}
    _serve(monkeypatch, row, valid=False)
    stale = client.post(f"/v1/questions/{row['id']}/review", json={"action": "approve"})
    assert (stale.status_code, stale.json()["detail"]) == (409, "citations_stale")
    _serve(monkeypatch, row, valid=True)
    ok = client.post(f"/v1/questions/{row['id']}/review", json={"action": "approve"}).json()
    assert ok["status"] == "active" and audited == ["question.review_approve"]
    _serve(monkeypatch, {**row, "status": "active"})
    again = client.post(f"/v1/questions/{row['id']}/review", json={"action": "approve"})
    assert again.status_code == 409


def test_edit_and_reject_are_checked_and_audited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, audited: list[str]  # noqa: F811
) -> None:
    row = {**stored(), "status": "draft"}
    _serve(monkeypatch, row)
    url = f"/v1/questions/{row['id']}/review"
    bad = client.post(url, json={"action": "edit", "options": ["A", "A", "B", "C", "D"]})
    assert (bad.status_code, bad.json()["detail"]) == (422, "sba_options_not_distinct")
    assert client.post(url, json={"action": "approve", "stem": "x"}).status_code == 422
    edited = client.post(url, json={"action": "edit", "stem": "Which diagnosis fits?"}).json()
    assert edited["status"] == "draft" and edited["item"]["stem"] == "Which diagnosis fits?"
    rejected = client.post(url, json={"action": "reject"}).json()
    assert rejected["status"] == "retired"
    assert audited == ["question.review_edit", "question.review_reject"]
    _serve(monkeypatch, {**row, "status": "active"}, open_exam=True)
    oracle = client.post(url, json={"action": "reject"})
    assert oracle.status_code == 409 and "key" not in oracle.json()


def test_generate_rejects_near_duplicates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    existing = uuid4()
    inserted: dict[str, dict[str, Any]] = {}

    async def gather(*_: Any, **__: Any) -> list[Any]:
        return EXCERPTS

    async def nearest(_s: Any, _u: Any, stem: str) -> DuplicateHit | None:
        return DuplicateHit(existing, 0.95, "trigram") if "twin" in stem else None

    async def insert_question(_s: Any, _t: Any, _u: Any, values: dict[str, Any]) -> UUID:
        qid = uuid4()
        inserted[str(qid)] = {**values, "id": qid, "created_at": NOW}
        return qid

    async def get_questions(*_: Any) -> dict[str, dict[str, Any]]:
        return inserted

    async def no_tenant(*_: Any) -> None:
        return None

    monkeypatch.setattr(retrieval, "gather_excerpts", gather)
    monkeypatch.setattr(dedupe, "embed_stems", lambda stems: (None, None))
    monkeypatch.setattr(dedupe, "nearest_by_trigram", nearest)
    monkeypatch.setattr(question_store, "insert_question", insert_question)
    monkeypatch.setattr(question_store, "get_questions", get_questions)
    monkeypatch.setattr(api, "set_database_tenant", no_tenant)
    items = [sba_item(), sba_item(stem="A twin stem. Most likely diagnosis?")]
    fake = FakeTransport({"question_generate": [{"items": [i.model_dump() for i in items]}],
                          "question_check": [PASS, PASS]})
    app.dependency_overrides[api.get_transport] = lambda: fake
    body = client.post("/v1/questions/generate", json={
        "source_ids": [str(uuid4())], "type": "sba", "exam_target": "frcr", "count": 2}).json()
    assert len(body["created"]) == 1 and body["duplicate_method"] == "trigram"
    assert body["rejected"] == [{"index": 1, "reasons": ["duplicate_of_existing"],
                                 "duplicate_of": str(existing), "similarity": 0.95}]


def test_submit_enqueues_pending_grading_after_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    seq = stored("seq")
    exam_id, queued = uuid4(), []
    row = {"id": exam_id, "mode": "exam", "config": {"free_text_ids": [str(seq["id"])]},
           "question_ids": [seq["id"]], "started_at": NOW, "deadline_at": None,
           "submitted_at": NOW, "revision": 1, "answers": {}, "just_submitted": True,
           "text_answers": {str(seq["id"]): "PAP"},
           "result": {"items": [{"question_id": str(seq["id"]), "status": "pending"}]}}

    async def submit(*_: Any) -> dict[str, Any]:
        return row

    async def get_questions(*_: Any) -> dict[str, dict[str, Any]]:
        return {str(seq["id"]): seq}

    monkeypatch.setattr(exams, "submit", submit)
    monkeypatch.setattr(question_store, "get_questions", get_questions)
    monkeypatch.setattr(exams_api, "enqueue_grading", lambda *a: queued.append(a))
    body = client.post(f"/v1/exams/{exam_id}/submit").json()
    assert body["text_answers"] == {str(seq["id"]): "PAP"}
    assert queued == [(TENANT, exam_id, [str(seq["id"])])]


def test_stats_recompute_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    qid = str(uuid4())

    async def recompute(*_: Any) -> dict[str, Any]:
        stat = {"question_id": qid, "attempts": 60, "correct": 59, "p_value": 0.98,
                "discrimination": 0.1, "discrimination_n": 30, "decision": "retire",
                "reason": "facility_too_high"}
        return {"computed": 1, "retired": [{"question_id": qid, "reason": "facility_too_high"}],
                "stats": [stat]}

    monkeypatch.setattr(item_stats, "recompute", recompute)
    body = client.post("/v1/questions/stats/recompute").json()
    assert body["retired"][0]["reason"] == "facility_too_high"


def test_new_routes_require_identity() -> None:
    app.dependency_overrides.clear()
    anonymous = TestClient(app)
    assert anonymous.get("/v1/questions/review").status_code == 401
    assert anonymous.post("/v1/questions/stats/recompute").status_code == 401
    assert anonymous.post(f"/v1/questions/{uuid4()}/review",
                          json={"action": "approve"}).status_code == 401


def test_migration_is_expand_only_with_forced_rls() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    assert 'revision = "20260926_0011"' in source
    assert 'down_revision = "20260926_0010"' in source
    assert 'TABLES = ("item_stats", "grading_jobs")' in source
    for statement in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                      "tenant_id = app.current_tenant_id()", "REVOKE ALL ON {table} FROM PUBLIC",
                      "embedding vector(1024)", "text_answers jsonb NOT NULL"):
        assert statement in upgrade
    assert "DROP " not in upgrade and "RENAME" not in upgrade
    assert "SECURITY DEFINER" not in upgrade
