"""Deterministic grading and the exam state machine (no database, no model)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from packages.assessment.grading import (
    ExamClosed,
    ExamExpired,
    ExamState,
    InvalidAnswer,
    StaleRevision,
    apply_seq_grade,
    autosave,
    exam_status,
    grade_exam,
    grade_sba,
)
from packages.assessment.models import PointGrade, SeqGrade

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
CITE = [{"ref": "E1", "kind": "chunk", "source_id": "s", "page_from": 1}]


def _sba(key: int = 2, topic: str = "Chest") -> dict[str, Any]:
    return {
        "id": uuid4(), "type": "sba", "topic": topic, "answer": {"key": key},
        "explanation": "why", "citations": CITE,
        "options": [{"text": f"o{i}", "explanation": f"e{i}", "citations": CITE}
                    for i in range(5)],
    }


def _exam(ids: list[UUID], **overrides: Any) -> ExamState:
    values: dict[str, Any] = {"mode": "exam", "question_ids": ids,
                              "deadline_at": NOW + timedelta(minutes=30),
                              "submitted_at": None, "revision": 0, "answers": {}}
    return ExamState(**{**values, **overrides})


def test_sba_is_exact_match_and_reveals_cited_explanations() -> None:
    question = _sba(key=2)
    right = grade_sba(question, 2)
    assert (right["correct"], right["score"], right["key"]) == (True, 1.0, 2)
    assert all(o["citations"] for o in right["option_explanations"])
    wrong = grade_sba(question, 0)
    assert (wrong["correct"], wrong["score"]) == (False, 0.0)
    assert grade_sba(question, None)["correct"] is False
    with pytest.raises(InvalidAnswer):
        grade_sba(question, 5)


def test_seq_grade_is_normalised_against_the_frozen_scheme() -> None:
    scheme = [{"point": "crazy paving", "marks": 4, "citations": CITE},
              {"point": "PAP", "marks": 4, "citations": CITE},
              {"point": "lavage", "marks": 2, "citations": CITE}]
    grade = SeqGrade(points=[
        PointGrade(scheme_index=0, status="matched", awarded=9, justification="a"),
        PointGrade(scheme_index=0, status="missed", awarded=0, justification="dup ignored"),
        PointGrade(scheme_index=1, status="missed", awarded=3, justification="b"),
        PointGrade(scheme_index=7, status="matched", awarded=5, justification="outside"),
    ], feedback="f")
    result = apply_seq_grade(scheme, grade)
    assert [p["awarded"] for p in result["points"]] == [4.0, 0.0, 0.0]  # clamp, missed, absent
    assert [p["status"] for p in result["points"]] == ["matched", "missed", "missed"]
    assert (result["score"], result["max_score"]) == (4.0, 10.0)
    assert all(p["citations"] == CITE for p in result["points"])


def test_autosave_compare_and_set_merges_and_clears() -> None:
    q1, q2 = uuid4(), uuid4()
    exam = _exam([q1, q2], answers={str(q1): 1})
    merged = autosave(exam, 0, {str(q2): 3, str(q1): None}, NOW)
    assert merged == {str(q2): 3}
    with pytest.raises(StaleRevision):
        autosave(exam, 1, {str(q2): 3}, NOW)


def test_autosave_rejects_foreign_questions_and_bad_options() -> None:
    q1 = uuid4()
    exam = _exam([q1])
    with pytest.raises(InvalidAnswer):
        autosave(exam, 0, {str(uuid4()): 1}, NOW)
    with pytest.raises(InvalidAnswer):
        autosave(exam, 0, {str(q1): 9}, NOW)


def test_deadline_and_submission_close_the_exam() -> None:
    q1 = uuid4()
    expired = _exam([q1], deadline_at=NOW - timedelta(seconds=1))
    assert exam_status(expired, NOW) == "expired"
    with pytest.raises(ExamExpired):
        autosave(expired, 0, {str(q1): 1}, NOW)
    submitted = _exam([q1], submitted_at=NOW)
    assert exam_status(submitted, NOW) == "submitted"
    with pytest.raises(ExamClosed):
        autosave(submitted, 0, {str(q1): 1}, NOW)
    practice = _exam([q1], mode="practice", deadline_at=None)
    assert exam_status(practice, NOW + timedelta(days=30)) == "active"


def test_exam_grading_scores_topics_and_unanswered_items() -> None:
    a, b, c = _sba(key=0, topic="Chest"), _sba(key=1, topic="Chest"), _sba(key=4, topic="Neuro")
    ids = [a["id"], b["id"], c["id"]]
    exam = _exam(ids, answers={str(a["id"]): 0, str(b["id"]): 3})
    result = grade_exam(exam, {str(q["id"]): q for q in (a, b, c)})
    assert (result["score"], result["max_score"], result["answered"]) == (1.0, 3.0, 2)
    assert result["percent"] == 33.3
    topics = {t["topic"]: t for t in result["by_topic"]}
    assert topics["Chest"] == {"topic": "Chest", "correct": 1, "total": 2, "answered": 2}
    assert topics["Neuro"]["answered"] == 0
    assert [item["key"] for item in result["items"]] == [0, 1, 4]


def test_deleted_question_counts_against_the_total() -> None:
    a = _sba(key=0)
    exam = _exam([a["id"], uuid4()], answers={str(a["id"]): 0})
    result = grade_exam(exam, {str(a["id"]): a})
    assert (result["score"], result["max_score"]) == (1.0, 2.0)
