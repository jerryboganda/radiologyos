"""Grade disputes (ADR 0029): scoring rules, roles, ownership, and the review flow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import assessment as api
from apps.api.app.assessment import dispute_service, dispute_store, exams
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.tests.test_assessment_api import TENANT, USER, FakeSession
from fastapi.testclient import TestClient
from packages.assessment.disputes import (
    DisputeRefused,
    apply_award,
    disputable_point,
    resolved_award,
)
from packages.assessment.exam_result import summarize

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
QUESTION = "30000000-0000-4000-8000-000000000001"


def _points() -> list[dict[str, Any]]:
    return [
        {"point": "names PAP", "marks": 2.0, "awarded": 0.0, "status": "missed",
         "justification": "not named", "citations": [{"kind": "chunk"}], "stage": "diagnosis"},
        {"point": "crazy paving", "marks": 2.0, "awarded": 2.0, "status": "matched",
         "justification": "", "citations": [], "stage": "findings"},
    ]


def result(**item: Any) -> dict[str, Any]:
    items = [{"question_id": QUESTION, "type": "image_case", "status": "graded", "score": 2.0,
              "max_score": 4.0, "points": _points(), "answer_text": "crazy paving",
              "topic": "PAP", **item}]
    return {**summarize(items, 1), "items": items}


def test_only_graded_written_points_below_full_marks_can_be_disputed() -> None:
    assert disputable_point(result(), QUESTION, 0)["point"] == "names PAP"
    cases = [(None, 0, "exam_not_submitted"), (result(), 1, "point_has_full_marks"),
             (result(), 5, "point_not_found"), (result(status="pending"), 0, "item_not_graded"),
             (result(type="sba"), 0, "not_an_auto_graded_point")]
    for stored, index, code in cases:
        with pytest.raises(DisputeRefused) as refused:
            disputable_point(stored, QUESTION, index)
        assert refused.value.code == code
    with pytest.raises(DisputeRefused):
        disputable_point(result(), str(uuid4()), 0)


def test_award_defaults_to_full_marks_and_stays_in_range() -> None:
    assert resolved_award(2.0, 0.0, None) == 2.0 and resolved_award(2.0, 0.0, 1.5) == 1.5
    for bad in (0.0, 2.5):
        with pytest.raises(DisputeRefused):
            resolved_award(2.0, 0.0, bad)


def test_accepting_recomputes_item_stage_and_exam_totals() -> None:
    before = result()
    after = apply_award(before, QUESTION, 0, 1.5, "d1")
    item = after["items"][0]
    assert item["score"] == 3.5 and after["score"] == 3.5 and after["percent"] == 87.5
    assert item["points"][0]["status"] == "partial"
    assert item["points"][0]["adjusted"] == {"dispute_id": "d1", "awarded_before": 0.0}
    assert {s["stage"]: s["score"] for s in item["stage_scores"]} == {
        "findings": 2.0, "diagnosis": 1.5}
    assert before["items"][0]["points"][0]["awarded"] == 0.0  # the input is not mutated
    full = apply_award(before, QUESTION, 0, 2.0, "d2")["items"][0]["points"][0]
    assert full["status"] == "matched"


def _dispute(**overrides: Any) -> dict[str, Any]:
    return {"id": uuid4(), "user_id": USER, "exam_id": uuid4(), "question_id": UUID(QUESTION),
            "point_index": 0, "reason": "I named it", "marks": 2.0, "awarded_before": 0.0,
            "awarded_after": None, "status": "open", "resolution_note": "", "created_at": NOW,
            "resolved_at": None, **overrides}


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    async def audit(_s: Any, _p: Any, action: str, _t: str, _i: str,
                    metadata: dict[str, Any] | None = None) -> None:
        seen.append((action, metadata or {}))

    monkeypatch.setattr(dispute_service, "audit", audit)
    yield seen
    app.dependency_overrides.clear()


def _client(role: str = "student", user: UUID = USER) -> TestClient:
    async def session() -> Any:
        yield FakeSession()

    app.dependency_overrides[api.principal_context] = lambda: Principal(user, TENANT, role)
    app.dependency_overrides[api.tenant_db_session] = session
    return TestClient(app)


def _exam_rows(monkeypatch: pytest.MonkeyPatch, owner: UUID, stored: dict[str, Any]) -> None:
    async def load_exam(_s: Any, user_id: UUID, exam_id: UUID, lock: bool = False) -> Any:
        return {"id": exam_id, "submitted_at": NOW, "result": stored} if user_id == owner \
            else None

    monkeypatch.setattr(exams, "load_exam", load_exam)


def test_routes_require_identity() -> None:
    anonymous = TestClient(app)
    assert anonymous.post(f"/v1/exams/{uuid4()}/disputes", json={}).status_code == 401
    assert anonymous.get("/v1/grade-disputes/review").status_code == 401


def test_owner_opens_a_dispute_once_and_others_cannot(
    monkeypatch: pytest.MonkeyPatch, audits: list[Any]
) -> None:
    _exam_rows(monkeypatch, USER, result())
    created: list[dict[str, Any]] = []

    async def insert(_s: Any, _t: Any, user_id: UUID, values: dict[str, Any]) -> Any:
        if created:
            return None
        created.append(_dispute(**values, user_id=user_id))
        return created[0]

    monkeypatch.setattr(dispute_store, "insert", insert)
    body = {"question_id": QUESTION, "point_index": 0, "reason": "  I named PAP  "}
    client = _client()
    response = client.post(f"/v1/exams/{uuid4()}/disputes", json=body)
    assert response.status_code == 201 and response.json()["status"] == "open"
    assert created[0]["reason"] == "I named PAP" and created[0]["awarded_before"] == 0.0
    assert audits[0][0] == "grade_dispute.opened" and "reason" not in audits[0][1]
    again = client.post(f"/v1/exams/{uuid4()}/disputes", json=body)
    assert (again.status_code, again.json()["detail"]) == (409, "already_disputed")
    full = client.post(f"/v1/exams/{uuid4()}/disputes", json={**body, "point_index": 1})
    assert full.json()["detail"] == "point_has_full_marks"
    stranger = _client(user=uuid4()).post(f"/v1/exams/{uuid4()}/disputes", json=body)
    assert stranger.status_code == 404


def test_queue_and_resolution_need_the_owner_admin_role(audits: list[Any]) -> None:
    client = _client("student")
    assert client.get("/v1/grade-disputes/review").status_code == 403
    resolve = client.post(f"/v1/grade-disputes/{uuid4()}/resolve", json={"action": "reject"})
    assert resolve.status_code == 403


def _resolve_store(monkeypatch: pytest.MonkeyPatch, dispute: dict[str, Any] | None,
                   saved: list[dict[str, Any]]) -> None:
    async def lock(*_: Any) -> Any:
        return dispute

    async def lock_exam_result(*_: Any) -> dict[str, Any]:
        return result()

    async def save_exam_result(_s: Any, _e: Any, stored: dict[str, Any]) -> None:
        saved.append(stored)

    async def resolve(_s: Any, _d: Any, status: str, awarded: Any, note: str, _r: Any) -> Any:
        assert dispute is not None
        return {**dispute, "status": status, "awarded_after": awarded, "resolution_note": note,
                "resolved_at": NOW}

    for name, fn in (("lock", lock), ("lock_exam_result", lock_exam_result),
                     ("save_exam_result", save_exam_result), ("resolve", resolve)):
        monkeypatch.setattr(dispute_store, name, fn)


def test_accept_adjusts_the_score_and_is_audited(
    monkeypatch: pytest.MonkeyPatch, audits: list[Any]
) -> None:
    saved: list[dict[str, Any]] = []
    _resolve_store(monkeypatch, _dispute(), saved)
    reply = _client("org_admin").post(f"/v1/grade-disputes/{uuid4()}/resolve",
                                      json={"action": "accept", "note": "fair"})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["dispute"]["status"] == "accepted" and body["dispute"]["awarded_after"] == 2.0
    assert body["exam_score"] == 4.0 and saved[0]["percent"] == 100.0
    action, meta = audits[-1]
    assert action == "grade_dispute.accepted"
    assert (meta["awarded_before"], meta["awarded_after"], meta["score_after"]) == (0.0, 2.0, 4.0)


def test_reject_closes_without_touching_the_score(
    monkeypatch: pytest.MonkeyPatch, audits: list[Any]
) -> None:
    saved: list[dict[str, Any]] = []
    _resolve_store(monkeypatch, _dispute(), saved)
    reply = _client("superadmin").post(f"/v1/grade-disputes/{uuid4()}/resolve",
                                       json={"action": "reject"}).json()
    assert reply["dispute"]["status"] == "rejected" and reply["exam_score"] is None
    assert saved == [] and audits[-1][0] == "grade_dispute.rejected"


def test_closed_missing_or_changed_disputes_are_refused(
    monkeypatch: pytest.MonkeyPatch, audits: list[Any]
) -> None:
    admin = _client("org_admin")
    for dispute, code in ((_dispute(status="accepted"), "dispute_closed"),
                          (None, "dispute_not_found"),
                          (_dispute(awarded_before=1.0), "point_changed_since_dispute")):
        _resolve_store(monkeypatch, dispute, [])
        reply = admin.post(f"/v1/grade-disputes/{uuid4()}/resolve", json={"action": "accept"})
        assert reply.json()["detail"] == code
    _resolve_store(monkeypatch, _dispute(), [])
    out_of_range = admin.post(f"/v1/grade-disputes/{uuid4()}/resolve",
                              json={"action": "accept", "awarded": 3})
    assert out_of_range.status_code == 422


def test_queue_shows_the_point_and_answer(
    monkeypatch: pytest.MonkeyPatch, audits: list[Any]
) -> None:
    async def open_queue(*_: Any) -> list[dict[str, Any]]:
        return [{**_dispute(), "result": result(), "stem": "Look at this", "topic": "PAP"}]

    monkeypatch.setattr(dispute_store, "open_queue", open_queue)
    body = _client("org_admin").get("/v1/grade-disputes/review").json()
    assert body[0]["point"] == "names PAP" and body[0]["answer_text"] == "crazy paving"
    assert body[0]["citations"] == [{"kind": "chunk"}] and "result" not in body[0]


MIGRATION = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
             / "20260926_0102_cards_results.py")


def test_migration_is_expand_only_with_forced_rls() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    assert 'revision = "20260926_0102"' in source and 'down_revision = "20260926_0101"' in source
    for statement in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                      "tenant_id = app.current_tenant_id()", "REVOKE ALL ON {table} FROM PUBLIC",
                      "UNIQUE (tenant_id, exam_id, question_id, point_index)",
                      "cards_claim_uidx", "cards_figure_uidx", "item_seconds jsonb",
                      "card_type text NOT NULL DEFAULT 'basic'"):
        assert statement in upgrade
    for forbidden in ("DROP TABLE", "DROP COLUMN", "RENAME", "SECURITY DEFINER"):
        assert forbidden not in upgrade
    # The only DROP is the in-place widening of the origin check.
    assert upgrade.count("DROP ") == 1
    assert "'manual', 'generated', 'weakness', 'claim', 'figure'" in upgrade
