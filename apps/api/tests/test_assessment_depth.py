"""Mixed exams, the async grading state machine, and owner review (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.assessment import generation
from apps.api.tests.test_assessment_api import FakeTransport
from apps.api.tests.test_assessment_validation import EXCERPTS, sba_item, seq_item
from packages.assessment import exam_result, grading_jobs, review
from packages.assessment.grading import ExamState, InvalidAnswer, autosave, merge_text
from packages.models.claude_code import ModelCallError, UsageLimitError

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
GRADE = {"points": [{"scheme_index": 0, "status": "matched", "awarded": 5,
                     "justification": "names PAP"}], "feedback": "Good."}


def stored(item_type: str = "sba", **overrides: Any) -> dict[str, Any]:
    item = sba_item(**overrides) if item_type == "sba" else seq_item(item_type, **overrides)
    row = generation.to_row(item, None, EXCERPTS, "fcps2_theory")
    return {**row, "id": uuid4(), "created_at": NOW, "status_reason": None}


def _exam(questions: list[dict[str, Any]], **overrides: Any) -> ExamState:
    free = frozenset(str(q["id"]) for q in questions if q["type"] != "sba")
    values: dict[str, Any] = {"mode": "exam", "question_ids": [q["id"] for q in questions],
                              "deadline_at": NOW + timedelta(minutes=30), "submitted_at": None,
                              "revision": 0, "free_text_ids": free}
    return ExamState(**{**values, **overrides})


def test_autosave_routes_options_and_text_to_the_right_items() -> None:
    sba, seq = stored(), stored("seq")
    exam = _exam([sba, seq], text_answers={str(seq["id"]): "old"})
    assert autosave(exam, 0, {str(sba["id"]): 2}, NOW) == {str(sba["id"]): 2}
    with pytest.raises(InvalidAnswer):
        autosave(exam, 0, {str(seq["id"]): 1}, NOW)
    assert merge_text(exam, {str(seq["id"]): "PAP"}) == {str(seq["id"]): "PAP"}
    assert merge_text(exam, {str(seq["id"]): "  "}) == {}
    with pytest.raises(InvalidAnswer):
        merge_text(exam, {str(sba["id"]): "text for an SBA"})
    with pytest.raises(InvalidAnswer):
        merge_text(exam, {str(seq["id"]): "x" * 8001})


def test_mixed_submission_grades_sba_now_and_leaves_written_items_pending() -> None:
    sba, seq, blank = stored(), stored("seq"), stored("viva")
    exam = _exam([sba, seq, blank], answers={str(sba["id"]): 0},
                 text_answers={str(seq["id"]): "PAP causes crazy paving"})
    result = exam_result.grade_exam(exam, {str(q["id"]): q for q in (sba, seq, blank)})
    statuses = {i["question_id"]: i["status"] for i in result["items"]}
    assert statuses == {str(sba["id"]): "graded", str(seq["id"]): "pending",
                        str(blank["id"]): "graded"}
    assert result["pending"] == 1 and result["grading"] == "pending"
    assert (result["score"], result["max_score"], result["answered"]) == (1.0, 11.0, 2)
    assert exam_result.pending_ids(result) == [str(seq["id"])]
    blank_item = next(i for i in result["items"] if i["question_id"] == str(blank["id"]))
    assert blank_item["score"] == 0.0 and all(p["citations"] for p in blank_item["points"])


def test_fill_item_completes_the_result() -> None:
    seq = stored("seq")
    exam = _exam([seq], text_answers={str(seq["id"]): "PAP"})
    result = exam_result.grade_exam(exam, {str(seq["id"]): seq})
    pending = result["items"][0]
    graded = {"score": 5.0, "max_score": 5.0, "points": [], "feedback": "ok"}
    filled = exam_result.fill_item(result, str(seq["id"]),
                                   exam_result.graded_free_text(pending, graded))
    assert (filled["score"], filled["percent"], filled["grading"]) == (5.0, 100.0, "complete")
    failed = exam_result.fill_item(result, str(seq["id"]),
                                   exam_result.failed_item(pending, "model_error"))
    assert failed["failed"] == 1 and failed["pending"] == 0 and failed["score"] == 0.0


def test_grading_state_machine_with_fake_transport() -> None:
    question = stored("seq")
    ok = grading_jobs.run_grading(FakeTransport({"seq_grade": [GRADE]}), question, "PAP", 0, 0)
    assert (ok.kind, ok.status) == ("graded", "graded") and ok.graded is not None
    assert ok.graded["score"] == 5.0 and ok.graded["points"][0]["citations"]
    limited = FakeTransport({"seq_grade": [UsageLimitError("limit")]})
    paused = grading_jobs.run_grading(limited, question, "PAP", 0, 3)
    assert (paused.kind, paused.status, paused.error) == ("deferred", "pending", "usage_limit")
    flaky = FakeTransport({"seq_grade": [ModelCallError("x"), ModelCallError("x")]})
    assert grading_jobs.run_grading(flaky, question, "PAP", 0, 1).kind == "retry"
    last = grading_jobs.run_grading(flaky, question, "PAP", grading_jobs.MAX_ERRORS - 1, 2)
    assert (last.kind, last.status) == ("failed", "failed")
    missing = grading_jobs.run_grading(None, question, "PAP", 0, 0)
    assert missing.kind == "deferred" and missing.error == "model_unavailable"
    exhausted = grading_jobs.run_grading(None, question, "PAP", 0, grading_jobs.MAX_RUNS - 1)
    assert exhausted.kind == "failed" and exhausted.error == "model_unavailable_exhausted"


def test_claimable_blocks_duplicates_until_the_run_looks_dead() -> None:
    assert grading_jobs.claimable("pending", NOW, NOW)
    assert not grading_jobs.claimable("running", NOW, NOW + timedelta(minutes=1))
    assert grading_jobs.claimable("running", NOW, NOW + grading_jobs.STALE_AFTER)
    assert not grading_jobs.claimable("graded", NOW - timedelta(days=1), NOW)
    assert not grading_jobs.claimable("failed", NOW - timedelta(days=1), NOW)


def test_review_edits_recheck_the_stored_item() -> None:
    question = stored()
    edited = review.apply_edits(question, {"stem": "Which diagnosis?", "key_index": 1})
    assert edited["answer"]["key"] == 1 and question["answer"]["key"] == 0
    assert review.stored_problems(edited) == []
    dup = review.apply_edits(question, {"options": ["A", "A", "B", "C", "D"]})
    assert "sba_options_not_distinct" in review.stored_problems(dup)
    banned = review.apply_edits(question, {"options": ["A", "B", "C", "D", "All of the above"]})
    assert "sba_all_or_none_of_the_above" in review.stored_problems(banned)
    with pytest.raises(ValueError):
        review.apply_edits(question, {"options": ["A", "B"]})
    assert review.stored_problems(review.apply_edits(stored("seq"), {"model_answer": "x"})) == []


def test_cited_targets_use_source_pages_and_figures() -> None:
    source, figure = uuid4(), uuid4()
    question = {
        "citations": [{"kind": "chunk", "source_id": str(source), "page_from": 2}],
        "options": [{"citations": [{"kind": "figure", "figure_id": str(figure)}]}],
        "answer": {"marking_scheme": [{"citations": [{"kind": "chunk"}]}]},
    }
    pages, figures = review.cited_targets(question)
    assert (source, 2) in pages and figures == {figure}
    assert (UUID(int=0), 0) in pages  # an unresolvable citation can never validate


def test_checker_reasons_surface_for_review() -> None:
    assert review.checker_reasons({"check": {"error": "check_failed"}}) == ["checker_error"]
    assert review.checker_reasons({"check": {"reasons": ["no_cueing: cue"]}}) == \
        ["no_cueing: cue"]
    assert review.checker_reasons({"passed": False, "check": {}}) == ["checker_failed"]
