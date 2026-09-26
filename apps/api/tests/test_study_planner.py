"""Exam-first planner and mastery rules (spec section 7)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from packages.study import planner
from packages.study.mastery import Attempt, band_for, mastery, weighted_accuracy
from packages.study.planner import DayInputs, TopicSignal, allocate_minutes, build_plan

TODAY = date(2026, 9, 26)  # a Saturday


def _topics() -> list[TopicSignal]:
    return [
        TopicSignal("CHEST", "Chest", mastery=0.2, days_untouched=None),
        TopicSignal("NEURO", "Neuro", mastery=0.9, days_untouched=1),
        TopicSignal("GI", "GI", mastery=0.4, recent_lapse=True, days_untouched=10),
        TopicSignal("MUSCULOSKELETAL", "MSK", mastery=0.6, days_untouched=40),
    ]


def _inputs(days: int, minutes: int = 90, due: int = 12, new: int = 30) -> DayInputs:
    return DayInputs(today=TODAY, exam_date=TODAY + timedelta(days=days), minutes=minutes,
                     due_count=due, new_available=new, topics=_topics(),
                     exam_targets=("fcps2_theory", "fcps2_toacs"))


@pytest.mark.parametrize(
    ("days", "phase"),
    [(365, "coverage"), (181, "coverage"), (180, "coverage_consolidation"),
     (90, "coverage_consolidation"), (89, "consolidation"), (30, "consolidation"),
     (29, "exam_mode"), (7, "exam_mode"), (6, "taper"), (0, "taper")],
)
def test_phase_by_days_remaining(days: int, phase: str) -> None:
    assert planner.phase_for(days) == phase


def test_priority_formula() -> None:
    signal = TopicSignal("GI", "GI", mastery=0.4, weight=0.1, recent_lapse=True,
                         days_untouched=15)
    assert planner.priority(signal, 0.5) == pytest.approx(0.1 * 0.6 * 1.5 * 1.5)
    assert planner.recency_decay(None) == 2.0
    assert planner.recency_decay(0) == 1.0 and planner.recency_decay(90) == 2.0


def test_ranking_prefers_weak_stale_and_lapsed_topics() -> None:
    ranked = planner.rank_topics(_topics())
    assert [t.code for t in ranked][:2] == ["CHEST", "GI"]
    assert ranked[-1].code == "NEURO"
    assert {t.band for t in ranked} == {"weak", "learning", "mastered"}


def test_allocation_always_sums_to_available_minutes() -> None:
    for phase in planner.MIX:
        for minutes in (0, 1, 15, 37, 60, 90, 120, 241, 600):
            for due in (0, 1, 10, 45, 200, 2000):
                alloc = allocate_minutes(minutes, phase, due)
                assert sum(alloc.values()) == minutes, (phase, minutes, due)
                assert all(v >= 0 for v in alloc.values())


def test_review_time_tracks_due_cards() -> None:
    idle = allocate_minutes(60, "coverage", 0)
    assert idle["review"] == 0 and idle["learn"] == 33 + 9
    busy = allocate_minutes(60, "coverage", 300)
    assert busy["review"] > 9 and busy["learn"] >= 33 // 2
    taper = allocate_minutes(60, "taper", 0)
    assert taper["learn"] == 0 and taper["test"] == 24 + 24


@pytest.mark.parametrize("days", [400, 120, 60, 20, 3])
@pytest.mark.parametrize("minutes", [15, 60, 90, 120])
def test_plan_never_exceeds_minutes(days: int, minutes: int) -> None:
    plan = build_plan(_inputs(days, minutes))
    assert sum(block["minutes"] for block in plan["blocks"]) == minutes
    assert all(block["minutes"] > 0 for block in plan["blocks"])
    learn = [b for b in plan["blocks"] if b["kind"] == "learn"]
    if learn:
        assert sum(t["minutes"] for t in learn[0]["topics"]) == learn[0]["minutes"]
        assert learn[0]["new_cards"] <= planner.NEW_CARD_CAP


def test_plan_shape_and_phase_rules() -> None:
    coverage = build_plan(_inputs(200))
    learn = next(b for b in coverage["blocks"] if b["kind"] == "learn")
    assert [t["code"] for t in learn["topics"]] == ["CHEST"]
    assert coverage["weight_policy"] == "equal_unvalidated"
    assert coverage["retention"] == 0.90 and coverage["days_remaining"] == 200

    consolidation = build_plan(_inputs(60))
    learn = next(b for b in consolidation["blocks"] if b["kind"] == "learn")
    slots = {t["code"]: t["slots"] for t in learn["topics"]}
    assert slots["CHEST"] == 2 and slots["MUSCULOSKELETAL"] == 1
    test_block = next(b for b in consolidation["blocks"] if b["kind"] == "test")
    assert test_block["mock_paper_suggested"] is True  # Saturday
    assert test_block["from_today_topics"] + test_block["interleaved_weak"] == \
        test_block["questions"]

    exam = build_plan(_inputs(20))
    viva = next(b for b in exam["blocks"] if b["kind"] == "viva")
    assert viva["format"] == "toacs_image_set" and exam["retention"] == 0.93


def test_taper_has_no_new_material() -> None:
    plan = build_plan(_inputs(3))
    assert plan["phase"] == "taper"
    assert "learn" not in {b["kind"] for b in plan["blocks"]}


def test_past_exam_date_clamps_to_taper() -> None:
    plan = build_plan(_inputs(-5))
    assert plan["days_remaining"] == 0 and plan["phase"] == "taper"


def test_plan_never_contains_a_pass_probability() -> None:
    text = json.dumps(build_plan(_inputs(100))).lower()
    assert "pass_prob" not in text and "probability" not in text


def test_mastery_formula_and_bands() -> None:
    m = mastery([Attempt(0, True), Attempt(0, False)], [0.9, 0.7], 0.5)
    assert m.score == pytest.approx(0.5 * 0.5 + 0.3 * 0.8 + 0.2 * 0.5)
    assert m.band == "learning"
    assert mastery([], [], 0.0).score == 0.0 and mastery([], [], 0.0).band == "weak"
    assert mastery([Attempt(0, True)], [1.0], 1.0).band == "mastered"
    assert band_for(0.5) == "learning" and band_for(0.79) == "learning"
    assert band_for(0.8) == "mastered" and band_for(0.49) == "weak"


def test_accuracy_half_life_is_fourteen_days() -> None:
    old_wrong_new_right = [Attempt(14, False), Attempt(0, True)]
    assert weighted_accuracy(old_wrong_new_right) == pytest.approx(1 / 1.5)
    assert weighted_accuracy([]) == 0.0
