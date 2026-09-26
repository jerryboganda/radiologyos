"""Unit tests for weight mapping, blended mastery, weekly reports, and baseline picking."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from packages.study.baseline import Candidate, per_system, pick, time_limit_minutes
from packages.study.mastery import (
    Attempt,
    coverage_share,
    mastery,
    question_attempt,
    review_attempt,
    weighted_accuracy,
)
from packages.study.report import (
    AttemptEvent,
    ReviewEvent,
    SystemStatus,
    WeekInputs,
    build_report,
    daily_minutes,
    retention_achieved,
)
from packages.study.weights import ApprovedWeight, map_weights

SYSTEMS = ["CHEST", "NEURO", "GI", "MSK"]


def _w(target: str, code: str, weight: float) -> ApprovedWeight:
    return ApprovedWeight(target, code, weight)


def test_no_approved_weights_falls_back_to_equal() -> None:
    mapped = map_weights([], ["fcps2_theory"], SYSTEMS)
    assert mapped.policy == "equal_unvalidated" and mapped.targets == ()
    assert mapped.weights == {code: 0.25 for code in SYSTEMS}


def test_target_weights_map_onto_systems_and_sum_to_one() -> None:
    rows = [_w("fcps2_theory", "CHEST", 0.4), _w("fcps2_theory", "NEURO", 0.3),
            _w("fcps2_theory", "GI", 0.2), _w("fcps2_theory", "MSK", 0.1),
            _w("frcr", "CHEST", 0.9), _w("fcps2_theory", "UNKNOWN", 0.5)]
    mapped = map_weights(rows, ["fcps2_theory"], SYSTEMS)
    assert mapped.policy == "past_paper_approved" and mapped.targets == ("fcps2_theory",)
    assert mapped.weights["CHEST"] == pytest.approx(0.4)
    assert sum(mapped.weights.values()) == pytest.approx(1.0)
    assert "UNKNOWN" not in mapped.weights


def test_multiple_targets_are_averaged_and_missing_systems_get_the_floor() -> None:
    rows = [_w("fcps2_theory", "CHEST", 0.5), _w("fcps2_theory", "NEURO", 0.5),
            _w("fcps2_toacs", "CHEST", 0.7), _w("fcps2_toacs", "NEURO", 0.1),
            _w("fcps2_toacs", "GI", 0.1), _w("fcps2_toacs", "MSK", 0.1)]
    mapped = map_weights(rows, ["fcps2_theory", "fcps2_toacs"], SYSTEMS)
    # theory: CHEST/NEURO 0.5, GI/MSK take the 0.5 floor -> 0.25 each after normalising.
    assert mapped.weights["CHEST"] == pytest.approx((0.25 + 0.7) / 2)
    assert mapped.weights["GI"] == pytest.approx((0.25 + 0.1) / 2)
    assert mapped.targets == ("fcps2_theory", "fcps2_toacs")


def test_all_aggregate_is_used_only_when_no_profile_target_is_approved() -> None:
    rows = [_w("all", "CHEST", 0.7), _w("all", "NEURO", 0.1), _w("all", "GI", 0.1),
            _w("all", "MSK", 0.1)]
    assert map_weights(rows, ["frcr"], SYSTEMS).targets == ("all",)
    with_target = rows + [_w("frcr", code, 0.25) for code in SYSTEMS]
    assert map_weights(with_target, ["frcr"], SYSTEMS).weights["CHEST"] == pytest.approx(0.25)


def test_question_attempts_outweigh_reviews_and_allow_partial_credit() -> None:
    reviews = [review_attempt(0, 3), review_attempt(0, 3)]
    wrong_question = question_attempt(0, 0.0, 1.0)
    assert weighted_accuracy(reviews + [wrong_question]) == pytest.approx(2 / 4)
    assert question_attempt(0, 3.0, 4.0).correct == pytest.approx(0.75)
    assert question_attempt(0, 5.0, 0.0).correct == 0.0
    assert review_attempt(0, 1).correct is False
    assert weighted_accuracy([Attempt(0, 0.5, 2.0)]) == pytest.approx(0.5)


def test_coverage_counts_cards_and_questions() -> None:
    assert coverage_share(0, 0, 0, 0) == 0.0
    assert coverage_share(4, 2, 6, 3) == pytest.approx(0.5)
    assert coverage_share(2, 5, 0, 0) == 1.0  # never above the material available
    m = mastery([question_attempt(0, 1.0, 1.0)], [], coverage_share(0, 0, 2, 1))
    assert m.accuracy == 1.0 and m.coverage == 0.5 and m.score == pytest.approx(0.6)


MONDAY = date(2026, 9, 21)
KARACHI = ZoneInfo("Asia/Karachi")


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 21 + day, hour, minute, tzinfo=KARACHI).astimezone(UTC)


def test_minutes_are_estimated_from_event_gaps() -> None:
    times = [_at(0, 7, 0), _at(0, 7, 2), _at(0, 7, 5), _at(0, 9, 0), _at(2, 20, 0)]
    per_day = daily_minutes(times, MONDAY, KARACHI)
    assert per_day[0] == pytest.approx(1 + 2 + 3 + 1)
    assert per_day[2] == pytest.approx(1)
    assert daily_minutes([_at(7, 8, 0)], MONDAY, KARACHI) == [0.0] * 7


def test_retention_counts_only_review_state_cards() -> None:
    reviews = [ReviewEvent(_at(0, 7, 0), 3, "review"), ReviewEvent(_at(0, 7, 1), 1, "review"),
               ReviewEvent(_at(0, 7, 2), 1, "new")]
    assert retention_achieved(reviews) == (0.5, 2)
    assert retention_achieved([]) == (None, 0)


def _system(code: str, mastery_: float, priority: float, material: bool = True,
            **kw: bool) -> SystemStatus:
    band = "weak" if mastery_ < 0.5 else "learning"
    return SystemStatus(code, code.title(), mastery_, band, priority, material, **kw)


def test_weekly_report_is_computed_without_a_model() -> None:
    systems = [_system("CHEST", 0.7, 0.05), _system("NEURO", 0.2, 0.2, recent_lapse=True),
               _system("GI", 0.1, 0.1), _system("MSK", 0.0, 0.3, False, started=False)]
    report = build_report(WeekInputs(
        week_start=MONDAY, zone=KARACHI,
        reviews=[ReviewEvent(_at(0, 7, 0), 3, "review"), ReviewEvent(_at(0, 7, 3), 1, "review")],
        attempts=[AttemptEvent(_at(1, 8, 0), 1.0, 1.0), AttemptEvent(_at(1, 8, 2), 0.0, 1.0)],
        systems=systems, target_retention=0.9, planned_minutes=600, days_remaining=100,
        phase="coverage_consolidation", weight_policy="equal_unvalidated"))
    assert report["minutes_studied"] == 7 and report["active_days"] == 2
    assert report["reviews"] == 2 and report["questions"] == 2
    assert report["question_accuracy"] == 0.5
    assert report["retention"] == {"achieved": 0.5, "target": 0.9, "eligible_reviews": 2,
                                   "met": False}
    assert [s["code"] for s in report["weakest"]] == ["GI", "NEURO", "CHEST"]
    assert [(f["code"], f["reason"]) for f in report["focus"]] == [
        ("MSK", "not started"), ("NEURO", "recent lapses"), ("GI", "weak mastery")]
    assert report["week_end"] == "2026-09-27"
    assert len(report["notes"]) == 3
    assert "probab" not in str(report).lower()


def test_baseline_pick_is_round_robin_across_systems() -> None:
    pool = [Candidate(uuid4(), code) for code in ["CHEST"] * 10 + ["NEURO"] * 2 + ["GI"]]
    chosen = pick(pool, 6, seed=7)
    codes = [c.curriculum_code for c in chosen]
    assert len(chosen) == 6 and len({c.question_id for c in chosen}) == 6
    assert sorted(codes[:3]) == ["CHEST", "GI", "NEURO"]
    assert codes.count("GI") == 1 and codes.count("NEURO") == 2
    assert pick(pool, 6, seed=7) == chosen
    assert len(pick(pool, 50, seed=1)) == len(pool)
    assert time_limit_minutes(20) == 30


def test_baseline_results_are_summarised_per_system() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    items = [{"question_id": str(a), "score": 1.0, "max_score": 1.0},
             {"question_id": str(b), "score": 0.0, "max_score": 1.0},
             {"question_id": str(c), "score": 1.0, "max_score": 1.0},
             {"question_id": str(uuid4()), "score": 1.0, "max_score": 1.0}]
    results = per_system(items, {str(a): "CHEST", str(b): "CHEST", str(c): "GI"})
    assert results == [
        {"code": "CHEST", "questions": 2, "correct": 1.0, "accuracy": 0.5},
        {"code": "GI", "questions": 1, "correct": 1.0, "accuracy": 1.0},
    ]


def test_week_boundaries_use_local_midnight() -> None:
    late_sunday_utc = datetime(2026, 9, 27, 18, 59, tzinfo=UTC)  # 23:59 in Karachi
    assert daily_minutes([late_sunday_utc], MONDAY, KARACHI)[6] == 1.0
    assert daily_minutes([late_sunday_utc + timedelta(minutes=2)], MONDAY, KARACHI) == [0.0] * 7
