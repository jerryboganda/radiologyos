"""Property-style checks for the FSRS-5 scheduler in packages/study/fsrs.py."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from packages.study import fsrs
from packages.study.fsrs import CardMemory, Rating

T0 = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)


def _reviewed(stability: float, difficulty: float, days_ago: int) -> CardMemory:
    last = T0 - timedelta(days=days_ago)
    return CardMemory(state="review", stability=stability, difficulty=difficulty,
                      due_at=last + timedelta(days=max(round(stability), 1)),
                      last_review_at=last, reps=3)


def test_retrievability_is_ninety_percent_at_one_stability() -> None:
    for s in (0.5, 1.0, 3.0, 40.0, 365.0):
        assert fsrs.retrievability(s, s) == pytest.approx(0.9)
        assert fsrs.next_interval(s, 0.9) == max(round(s), 1)


def test_retrievability_decreases_with_time() -> None:
    values = [fsrs.retrievability(t, 10.0) for t in range(0, 200, 5)]
    assert values[0] == 1.0
    assert all(a > b for a, b in zip(values, values[1:], strict=False))


def test_first_review_uses_published_defaults() -> None:
    good = fsrs.review(CardMemory(), Rating.GOOD, T0)
    assert good.card.stability == pytest.approx(3.173)
    assert good.card.difficulty == pytest.approx(7.1949 - 2.912 + 1, abs=1e-3)
    assert good.scheduled_days == 3 and good.card.state == "review"
    assert good.card.due_at == T0 + timedelta(days=3)


def test_first_review_intervals_are_ordered_by_rating() -> None:
    outcomes = [fsrs.review(CardMemory(), rating, T0) for rating in Rating]
    days = [o.scheduled_days for o in outcomes]
    assert days[0] == 0 and days[1] < days[2] < days[3]
    assert outcomes[0].card.due_at == T0 + fsrs.RELEARN_DELAY
    assert outcomes[0].card.lapses == 0  # a new card cannot lapse


def test_repeated_good_grows_intervals_and_due_dates() -> None:
    card, now = CardMemory(), T0
    intervals, dues = [], []
    for _ in range(8):
        outcome = fsrs.review(card, Rating.GOOD, now)
        card = outcome.card
        intervals.append(outcome.scheduled_days)
        assert card.due_at is not None
        dues.append(card.due_at)
        now = card.due_at
    assert all(a < b for a, b in zip(intervals, intervals[1:], strict=False))
    assert all(a < b for a, b in zip(dues, dues[1:], strict=False))
    assert card.reps == 8 and card.lapses == 0


def test_again_on_review_card_shrinks_stability_and_counts_a_lapse() -> None:
    card = _reviewed(20.0, 5.0, 20)
    outcome = fsrs.review(card, Rating.AGAIN, T0)
    assert outcome.card.stability < card.stability
    assert outcome.card.lapses == 1 and outcome.card.state == "relearning"
    assert outcome.card.due_at == T0 + fsrs.RELEARN_DELAY
    assert outcome.retrievability == pytest.approx(0.9)


def test_random_states_keep_invariants() -> None:
    rng = random.Random(20260926)
    for _ in range(500):
        s = rng.uniform(0.1, 400.0)
        d = rng.uniform(1.0, 10.0)
        card = _reviewed(s, d, rng.randint(1, int(3 * s) + 2))
        by_rating = {r: fsrs.review(card, r, T0) for r in Rating}
        stab = {r: o.card.stability for r, o in by_rating.items()}
        diff = {r: o.card.difficulty for r, o in by_rating.items()}
        assert stab[Rating.AGAIN] <= s < stab[Rating.HARD] <= stab[Rating.GOOD]
        assert stab[Rating.GOOD] <= stab[Rating.EASY]
        assert diff[Rating.AGAIN] >= diff[Rating.HARD] >= diff[Rating.GOOD] >= diff[Rating.EASY]
        assert all(1.0 <= v <= 10.0 for v in diff.values())
        days = [by_rating[r].scheduled_days for r in (Rating.HARD, Rating.GOOD, Rating.EASY)]
        assert 1 <= days[0] <= days[1] <= days[2] <= fsrs.MAX_INTERVAL_DAYS


def test_same_day_review_uses_short_term_stability() -> None:
    first = fsrs.review(CardMemory(), Rating.AGAIN, T0).card
    again = fsrs.review(first, Rating.AGAIN, T0 + timedelta(minutes=10))
    good = fsrs.review(first, Rating.GOOD, T0 + timedelta(minutes=10))
    assert again.card.stability < first.stability < good.card.stability
    assert again.elapsed_days == 0 and again.retrievability is None


def test_higher_retention_shortens_intervals() -> None:
    assert fsrs.next_interval(30.0, 0.93) < fsrs.next_interval(30.0, 0.90)
    assert fsrs.retention_for(31) == 0.90 and fsrs.retention_for(30) == 0.93
    assert fsrs.retention_for(None) == 0.90
    with pytest.raises(ValueError):
        fsrs.next_interval(3.0, 1.0)


def test_review_before_last_review_is_rejected() -> None:
    card = _reviewed(5.0, 5.0, 0)
    with pytest.raises(ValueError):
        fsrs.review(card, Rating.GOOD, T0 - timedelta(hours=1))
    with pytest.raises(ValueError):
        fsrs.review(card, 5, T0)


def test_current_retrievability_for_new_and_reviewed_cards() -> None:
    assert fsrs.current_retrievability(CardMemory(), T0) == 0.0
    card = _reviewed(10.0, 5.0, 10)
    assert fsrs.current_retrievability(card, T0) == pytest.approx(0.9)
