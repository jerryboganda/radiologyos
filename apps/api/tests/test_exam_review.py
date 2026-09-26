"""Exam results review (ADR 0029): time, confidence, calibration, and the grading lease."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from apps.api.app.api import exams as exams_api
from apps.api.app.assessment import exams, grading_store
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.tests.test_assessment_api import client  # noqa: F401
from apps.api.tests.test_assessment_depth import NOW, stored
from fastapi.testclient import TestClient
from packages.assessment.exam_result import fill_item, grade_exam, graded_free_text
from packages.assessment.exam_review import (
    ReviewInputError,
    calibration,
    merge_confidence,
    merge_seconds,
    timing,
)
from packages.assessment.grading import ExamState, InvalidAnswer
from packages.assessment.grading_jobs import STALE_AFTER


def test_seconds_only_grow_and_are_capped_by_elapsed_time() -> None:
    allowed = {"a", "b"}
    merged = merge_seconds({"a": 40}, {"a": 30, "b": 90}, allowed, elapsed_seconds=600)
    assert merged == {"a": 40, "b": 90}
    assert merge_seconds({}, {"a": 5000}, allowed, elapsed_seconds=100) == {"a": 160}
    with pytest.raises(ReviewInputError):
        merge_seconds({}, {"z": 1}, allowed, 100)
    with pytest.raises(ReviewInputError):
        merge_seconds({}, {"a": -1}, allowed, 100)


def test_confidence_sets_clears_and_rejects_out_of_range() -> None:
    allowed = {"a", "b"}
    assert merge_confidence({"a": 1}, {"a": None, "b": 3}, allowed) == {"b": 3}
    for bad in ({"a": 4}, {"a": 0}, {"z": 2}):
        with pytest.raises(ReviewInputError):
            merge_confidence({}, bad, allowed)


def _exam(questions: list[dict[str, Any]], **fields: Any) -> ExamState:
    return ExamState(mode="exam", question_ids=[q["id"] for q in questions],
                     deadline_at=NOW + timedelta(minutes=30), submitted_at=None, revision=1,
                     **fields)


def test_grade_exam_annotates_items_and_summarises_review() -> None:
    right, wrong, essay = stored(), stored(), stored("seq")
    ids = [str(q["id"]) for q in (right, wrong, essay)]
    state = _exam([right, wrong, essay], answers={ids[0]: 0, ids[1]: 3},
                  text_answers={ids[2]: "PAP"}, free_text_ids=frozenset({ids[2]}),
                  item_seconds={ids[0]: 30, ids[1]: 90, ids[2]: 300},
                  confidence={ids[0]: 3, ids[1]: 3, ids[2]: 2})
    result = grade_exam(state, {q: r for q, r in zip(ids, (right, wrong, essay), strict=True)})
    items = {i["question_id"]: i for i in result["items"]}
    assert items[ids[1]]["time_seconds"] == 90 and items[ids[1]]["confidence"] == 3
    review = result["review"]
    assert review["timing"]["total_seconds"] == 420 and review["timing"]["timed_items"] == 3
    assert review["timing"]["slowest"][0] == {"question_id": ids[2], "seconds": 300}
    cal = review["calibration"]
    assert cal["rated"] == 2  # the written item is pending, so it is left out
    assert cal["confidently_wrong"] == 1 and cal["bias"] == pytest.approx(0.4)
    graded = graded_free_text(items[ids[2]], {"points": [], "score": 2.5, "max_score": 5.0,
                                               "feedback": "ok"})
    filled = fill_item(result, ids[2], graded)
    assert filled["review"]["calibration"]["rated"] == 3
    medium = next(level for level in filled["review"]["calibration"]["levels"]
                  if level["level"] == 2)
    assert medium["count"] == 1 and medium["mean_score"] == 0.5


def test_review_handles_untimed_and_unrated_items() -> None:
    items = [{"question_id": "q", "status": "graded", "score": 1.0, "max_score": 1.0}]
    assert timing(items)["mean_seconds"] is None
    assert calibration(items)["bias"] is None and calibration(items)["rated"] == 0


def test_merge_review_turns_bad_input_into_invalid_answer() -> None:
    question = stored()
    state = _exam([question])
    row = {"started_at": NOW}
    with pytest.raises(InvalidAnswer):
        exams._merge_review(row, state, {"confidence": {str(uuid4()): 2}}, NOW)
    seconds, confidence = exams._merge_review(
        row, state, {"item_seconds": {str(question["id"]): 20},
                     "confidence": {str(question["id"]): 1}}, NOW + timedelta(minutes=1))
    assert seconds == {str(question["id"]): 20} and confidence == {str(question["id"]): 1}


def test_autosave_route_passes_time_and_confidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    seen: list[Any] = []
    qid = str(uuid4())

    async def save(_s: Any, _u: Any, _e: Any, revision: int, answers: Any, text: Any,
                   extras: Any) -> dict[str, Any]:
        seen.append(extras)
        return {"revision": revision + 1, "answers": answers, "text_answers": {},
                "item_seconds": extras["item_seconds"], "confidence": {qid: 2},
                "deadline_at": None}

    monkeypatch.setattr(exams, "save_answers", save)
    body = {"revision": 0, "answers": {}, "item_seconds": {qid: 12}, "confidence": {qid: 2}}
    reply = client.put(f"/v1/exams/{uuid4()}/answers", json=body).json()
    assert seen == [{"item_seconds": {qid: 12}, "confidence": {qid: 2}}]
    assert reply["item_seconds"] == {qid: 12} and reply["confidence"] == {qid: 2}
    bad = client.put(f"/v1/exams/{uuid4()}/answers",
                     json={**body, "confidence": {qid: "high"}})
    assert bad.status_code == 422
    app.dependency_overrides.clear()


class CaptureSession:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> list[Any]:
        self.sql.append(str(statement))
        self.params.append(params)
        return []


async def test_reading_an_exam_never_refreshes_a_live_grading_lease() -> None:
    session = CaptureSession()
    pending_before, running_before = NOW - timedelta(minutes=10), NOW - timedelta(minutes=15)
    await grading_store.stale_pending(session, uuid4(), uuid4(),  # type: ignore[arg-type]
                                      pending_before, running_before)
    sql = " ".join(session.sql[0].split())
    assert "SET status = 'pending'" in sql and "updated_at = now()" not in sql
    assert "(status = 'running' AND updated_at < :rb)" in sql
    assert "(status = 'pending' AND updated_at < :pb)" in sql
    assert session.params[0]["rb"] == running_before and session.params[0]["pb"] == pending_before


async def test_exam_read_uses_the_worker_takeover_window(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    async def stale(_s: Any, _u: Any, _e: Any, pending: Any, running: Any) -> list[Any]:
        seen.append(running - pending)
        return []

    monkeypatch.setattr(grading_store, "stale_pending", stale)
    principal = Principal(user_id=uuid4(), tenant_id=uuid4())
    row = {"id": uuid4(), "result": {"items": [{"question_id": "q", "status": "pending"}]}}
    await exams_api._to_enqueue(None, principal, row)  # type: ignore[arg-type]
    assert seen == [exams_api.REQUEUE_AFTER - STALE_AFTER]
