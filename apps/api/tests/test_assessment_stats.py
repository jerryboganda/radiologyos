"""Item statistics math, retirement rules, and duplicate thresholds (pure code)."""

from __future__ import annotations

import statistics

import pytest
from packages.assessment import duplicates, stats
from packages.assessment.stats import AttemptRow, ItemStat


def _stat(attempts: int, p: float | None, disc: float | None = 0.4, n: int = 40) -> ItemStat:
    return ItemStat("q", attempts, 0, p, disc, n)


def test_point_biserial_matches_pearson_and_handles_degenerate_input() -> None:
    item, rest = [1.0, 1.0, 0.0, 0.0, 1.0], [0.9, 0.7, 0.4, 0.2, 0.3]
    assert stats.point_biserial(item, rest) == pytest.approx(
        statistics.correlation(item, rest), abs=1e-4)
    assert stats.point_biserial([1, 1, 1], [0.2, 0.5, 0.9]) is None  # no item variance
    assert stats.point_biserial([1, 0], [0.5, 0.5]) is None  # no rest variance
    assert stats.point_biserial([1], [0.5]) is None
    assert stats.point_biserial([1, 0], [0.5]) is None


def test_facility_counts_partial_credit_and_full_marks() -> None:
    rows = [AttemptRow("a", None, 1, 1), AttemptRow("a", None, 0, 1),
            AttemptRow("b", None, 6, 10), AttemptRow("b", None, 10, 10)]
    computed = stats.compute_stats(rows)
    assert computed["a"].p_value == 0.5 and computed["a"].correct == 1
    assert computed["b"].p_value == 0.8 and computed["b"].correct == 1
    assert computed["a"].discrimination is None and computed["a"].discrimination_n == 0


def test_discrimination_uses_rest_of_exam_score() -> None:
    rows: list[AttemptRow] = []
    # Strong candidates get "good" right and "noise" wrong; weak ones the reverse.
    for exam, strong in enumerate([True, True, True, False, False, False]):
        e = f"e{exam}"
        rows.append(AttemptRow("good", e, 1.0 if strong else 0.0, 1))
        rows.append(AttemptRow("noise", e, 0.0 if strong else 1.0, 1))
        for k in range(4):
            rows.append(AttemptRow(f"f{k}", e, 1.0 if strong else 0.0, 1))
    computed = stats.compute_stats(rows)
    assert computed["good"].discrimination is not None and computed["good"].discrimination > 0.9
    assert computed["noise"].discrimination is not None and computed["noise"].discrimination < 0
    assert computed["good"].discrimination_n == 6


def test_retirement_waits_for_fifty_attempts() -> None:
    assert stats.retirement_reason(_stat(49, 0.99)) is None
    assert stats.decision(_stat(49, 0.99)) == "insufficient"


@pytest.mark.parametrize(("p", "disc", "n", "reason"), [
    (0.86, 0.5, 40, "facility_too_high"),
    (0.24, 0.5, 40, "facility_too_low"),
    (0.60, 0.19, 40, "discrimination_too_low"),
    (0.60, None, 40, "discrimination_too_low"),
    (0.60, 0.05, 19, None),  # too few exam responses to judge discrimination
    (0.85, 0.20, 40, None),  # boundaries stay live
    (0.25, 0.20, 40, None),
])
def test_retirement_thresholds(p: float, disc: float | None, n: int, reason: str | None) -> None:
    stat = _stat(50, p, disc, n)
    assert stats.retirement_reason(stat) == reason
    assert stats.decision(stat) == ("retire" if reason else "keep")


def test_duplicate_thresholds_and_normalisation() -> None:
    assert duplicates.normalize_stem("  A 62-year-old  man; HRCT shows...  ") == \
        "a 62 year old man hrct shows"
    assert duplicates.is_duplicate(0.92, "embedding")
    assert not duplicates.is_duplicate(0.9199, "embedding")
    assert duplicates.is_duplicate(0.9, "trigram")
    assert not duplicates.is_duplicate(0.89, "trigram")
    assert not duplicates.is_duplicate(None, "trigram")
    assert duplicates.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert duplicates.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert duplicates.cosine([], []) == 0.0
    assert duplicates.vector_literal([0.5, -1]) == "[0.5000000,-1.0000000]"
