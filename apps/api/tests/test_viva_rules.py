"""Viva persona rules, stop rules, scoring, citation fail-closed, staged-case helpers."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from apps.api.app.assessment import weakness
from apps.api.tests.test_assessment_validation import EXCERPTS, SUPPLIED
from apps.api.tests.viva_fakes import NOW, expected, grade, staged_case
from packages.assessment import staged_case as staged
from packages.assessment import viva
from packages.assessment.exam_result import graded_free_text
from packages.assessment.grading import apply_seq_grade
from packages.assessment.models import SeqGrade
from packages.assessment.viva_models import ExaminerQuestion, StagedCase, VivaTurnGrade

BY_REF = viva.citation_map(EXCERPTS)


def test_good_answers_escalate_one_level_and_cap_at_five() -> None:
    assert viva.next_move("good", 1, 1) == viva.Move("escalate", 2, 0)
    assert viva.next_move("good", 5, 0).level == 5


def test_weak_answers_probe_and_misses_count() -> None:
    assert viva.next_move("partial", 3, 1) == viva.Move("probe", 3, 0)
    assert viva.next_move("miss", 3, 0) == viva.Move("probe", 2, 1)
    assert viva.next_move("miss", 1, 1) == viva.Move("probe", 1, 2)


def test_stop_rules_misses_turns_and_time() -> None:
    later = NOW + timedelta(minutes=5)
    assert viva.stop_reason(2, 8, 2, NOW, later) == "two_consecutive_misses"
    assert viva.stop_reason(8, 8, 0, NOW, later) == "max_turns"
    assert viva.stop_reason(3, 8, 0, later, later) == "time_up"
    assert viva.stop_reason(3, 8, 1, NOW, None) is None


@pytest.mark.parametrize(("fraction", "unsafe", "verdict"), [
    (1.0, False, "good"), (0.75, False, "good"), (0.5, False, "partial"),
    (0.3, False, "miss"), (1.0, True, "miss"),
])
def test_verdict_from_expected_points(fraction: float, unsafe: bool, verdict: str) -> None:
    assert viva.verdict_of(fraction, unsafe) == verdict


def test_evaluation_is_normalised_against_frozen_points() -> None:
    raw = grade(("matched",))
    raw["points"] += [{"index": 0, "status": "missed", "justification": "dup"},
                      {"index": 9, "status": "matched", "justification": "outside"}]
    result = viva.evaluate_turn(VivaTurnGrade.model_validate(raw), expected(), BY_REF)
    assert [p["status"] for p in result["points"]] == ["matched", "missed"]
    assert result["verdict"] == "partial" and result["scores"]["knowledge"] == 0.5
    assert result["scores"]["reasoning"] == 0.75 and result["teaching_point"]["citations"]


def test_unsafe_answer_is_a_miss_even_when_points_match() -> None:
    result = viva.evaluate_turn(VivaTurnGrade.model_validate(grade(unsafe=True)),
                                expected(), BY_REF)
    assert result["verdict"] == "miss"


def test_citations_fail_closed() -> None:
    q = ExaminerQuestion.model_validate({
        "question": "Q", "hint": "", "expected_points": [
            {"point": "cited", "citations": ["E1", "E99"]},
            {"point": "uncited", "citations": ["E99"]}]})
    points = viva.cited_expected(q, BY_REF)
    assert [p["point"] for p in points] == ["cited"]
    assert [c["ref"] for c in points[0]["citations"]] == ["E1"]
    bad = VivaTurnGrade.model_validate(grade(teach_cite="E42"))
    assert viva.evaluate_turn(bad, expected(), BY_REF)["teaching_point"] is None
    only_bad = ExaminerQuestion.model_validate({"question": "Q", "hint": "", "expected_points": [
        {"point": "x", "citations": ["Z1"]}]})
    assert viva.cited_expected(only_bad, BY_REF) == []


def _graded(turn_no: int, verdict: str, level: int, scores: dict[str, float],
            teach: str | None = None) -> dict[str, Any]:
    point = {"text": teach, "citations": [{"ref": "E1"}]} if teach else None
    return {"turn_no": turn_no, "level": level, "status": "graded", "stage": None,
            "prompt": "Q", "evaluation": {"verdict": verdict, "scores": scores,
                                          "teaching_point": point, "points": []}}


def test_debrief_scores_each_competency_and_orders_teaching_points() -> None:
    turns = [
        _graded(1, "good", 1, {"knowledge": 1.0, "reasoning": 0.5, "communication": 1.0}, "A"),
        _graded(2, "miss", 2, {"knowledge": 0.0, "reasoning": 0.25, "communication": 0.5}, "B"),
        {"turn_no": 3, "level": 1, "status": "skipped", "evaluation": None},
    ]
    result = viva.debrief(turns, "two_consecutive_misses", "viva")
    by_key = {c["key"]: c["percent"] for c in result["competencies"]}
    assert by_key == {"knowledge": 50.0, "reasoning": 37.5, "communication": 75.0}
    assert result["overall_percent"] == 54.2 and result["turns_answered"] == 2
    assert [p["text"] for p in result["teaching_points"]] == ["B", "A"]
    assert result["level_reached"] == 1 and result["weak_turns"] == [2]


def test_empty_debrief_is_zero_not_an_error() -> None:
    result = viva.debrief([], "ended_by_candidate", "viva")
    assert result["overall_percent"] == 0.0
    assert all(c["percent"] is None for c in result["competencies"])


def test_staged_case_checks_order_and_citations() -> None:
    ok = StagedCase.model_validate(staged_case())
    assert staged.validate_staged(ok, SUPPLIED) == []
    shuffled = StagedCase.model_validate(staged_case(order=tuple(reversed(staged.STAGES))))
    assert "stages_out_of_order" in staged.validate_staged(shuffled, SUPPLIED)
    uncited = StagedCase.model_validate(staged_case(cite="E77"))
    assert "citation_not_supplied" in staged.validate_staged(uncited, SUPPLIED)


def test_stage_rubric_is_tagged_and_resolved() -> None:
    rubric = staged.stage_rubric(StagedCase.model_validate(staged_case()), EXCERPTS)
    assert [r["stage"] for r in rubric] == list(staged.STAGES)
    point = rubric[2]["marking_scheme"][0]
    assert point["stage"] == "diagnosis" and point["citations"][0]["ref"] == "E1"
    answer = staged.with_stages({"model_answer": "x"}, rubric)
    assert len(answer["marking_scheme"]) == 5 and answer["stages"][0]["prompt"]


def test_stage_evaluation_reveals_cited_model_answer() -> None:
    rubric = staged.stage_rubric(StagedCase.model_validate(staged_case()), EXCERPTS)[1]
    result = staged.stage_evaluation(rubric, SeqGrade.model_validate(
        {"points": [{"scheme_index": 0, "status": "partial", "awarded": 9,
                     "justification": "j"}], "feedback": "f"}))
    assert result["score"] == 2.0 and result["max_score"] == 2.0
    assert result["model_answer"] == "findings answer"
    assert result["scores"] == {"knowledge": 1.0} and result["teaching_point"]["citations"]


def test_structured_answers_round_trip_and_score_by_stage() -> None:
    text = staged.compose_answer({"describe": "CT", "diagnosis": "PAP", "findings": " "})
    assert text == "[describe]\nCT\n[diagnosis]\nPAP"
    assert staged.split_answer("preamble\n" + text) == {"describe": "CT", "diagnosis": "PAP"}
    scheme = [{"point": "CT", "marks": 1, "citations": [], "stage": "describe"},
              {"point": "PAP", "marks": 2, "citations": [], "stage": "diagnosis"}]
    graded = apply_seq_grade(scheme, SeqGrade.model_validate({"points": [
        {"scheme_index": 1, "status": "matched", "awarded": 2, "justification": "j"}],
        "feedback": ""}))
    assert graded["points"][1]["stage"] == "diagnosis"
    item = graded_free_text({"question_id": "q"}, graded)
    assert item["stage_scores"] == [{"stage": "describe", "score": 0.0, "max_score": 1.0},
                                    {"stage": "diagnosis", "score": 2.0, "max_score": 2.0}]
    plain = apply_seq_grade([{"point": "p", "marks": 1, "citations": []}],
                            SeqGrade(points=[], feedback=""))
    assert "stage" not in plain["points"][0]
    assert "stage_scores" not in graded_free_text({"question_id": "q"}, plain)


class _Nested:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: Any) -> None:
        return None


class _Db:
    def begin_nested(self) -> _Nested:
        return _Nested()


def test_weak_turns_reach_registered_sinks_and_failures_are_contained() -> None:
    row = {"id": uuid4(), "tenant_id": uuid4(), "user_id": uuid4(), "kind": "viva",
           "topic": "PAP"}
    missed = _graded(2, "miss", 1, {"knowledge": 0.0}, "Teach")
    missed["evaluation"]["points"] = [
        {"status": "missed", "citations": [{"ref": "E1", "chunk_id": "c1"}]},
        {"status": "matched", "citations": [{"ref": "E2", "chunk_id": "c2"}]}]
    areas = weakness.weak_areas(row, [_graded(1, "good", 1, {}), missed])
    assert [(a.turn_no, a.verdict) for a in areas] == [(2, "miss")]
    assert [c.get("chunk_id") for c in areas[0].citations] == ["c1", None]
    seen: list[Any] = []

    async def sink(_db: Any, got: Any) -> None:
        seen.extend(got)

    async def broken(_db: Any, _got: Any) -> None:
        raise RuntimeError("sink down")

    weakness.register_weakness_sink(sink)
    weakness.register_weakness_sink(broken)
    try:
        accepted = asyncio.run(weakness.report_weak_areas(_Db(), areas))  # type: ignore[arg-type]
    finally:
        weakness.unregister_weakness_sink(sink)
        weakness.unregister_weakness_sink(broken)
    assert accepted == 1 and seen == areas
    assert asyncio.run(weakness.report_weak_areas(_Db(), [])) == 0  # type: ignore[arg-type]
