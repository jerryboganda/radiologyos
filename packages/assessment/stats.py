"""Item statistics and retirement rules (spec section 8, step 7). Pure code.

Facility (p-value) is the mean fraction of marks earned per attempt. The
discrimination index is the point-biserial correlation between an item's score
fraction and the candidate's rest-of-exam score fraction (the exam total with
this item removed), so it is only defined from exam attempts. After at least
``MIN_ATTEMPTS`` attempts an item stays live only while facility lies within
``FACILITY_MIN``..``FACILITY_MAX`` and, once enough exam responses exist to
judge it, discrimination is at least ``MIN_DISCRIMINATION``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MIN_ATTEMPTS = 50
FACILITY_MIN = 0.25
FACILITY_MAX = 0.85
MIN_DISCRIMINATION = 0.20
MIN_DISCRIMINATION_SAMPLE = 20


@dataclass(frozen=True, slots=True)
class AttemptRow:
    question_id: str
    exam_id: str | None
    score: float
    max_score: float

    @property
    def fraction(self) -> float:
        return min(1.0, max(0.0, self.score / self.max_score)) if self.max_score > 0 else 0.0


@dataclass(frozen=True, slots=True)
class ItemStat:
    question_id: str
    attempts: int
    correct: int
    p_value: float | None
    discrimination: float | None
    discrimination_n: int


def facility(fractions: Sequence[float]) -> float | None:
    return round(sum(fractions) / len(fractions), 4) if fractions else None


def point_biserial(item: Sequence[float], rest: Sequence[float]) -> float | None:
    """Pearson correlation of item score with rest score; None when undefined.

    For a dichotomous item this is exactly the point-biserial coefficient; for
    partial-credit items it is the item-rest correlation.
    """
    n = len(item)
    if n != len(rest) or n < 2:
        return None
    mean_i, mean_r = sum(item) / n, sum(rest) / n
    cov = sum((a - mean_i) * (b - mean_r) for a, b in zip(item, rest, strict=True))
    var_i = sum((a - mean_i) ** 2 for a in item)
    var_r = sum((b - mean_r) ** 2 for b in rest)
    if var_i <= 0 or var_r <= 0:
        return None
    return round(max(-1.0, min(1.0, cov / math.sqrt(var_i * var_r))), 4)


def rest_pairs(rows: Iterable[AttemptRow]) -> dict[str, list[tuple[float, float]]]:
    """Per question: (item fraction, rest-of-exam fraction) for every exam response."""
    by_exam: dict[str, list[AttemptRow]] = defaultdict(list)
    for row in rows:
        if row.exam_id is not None:
            by_exam[row.exam_id].append(row)
    pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for members in by_exam.values():
        total = sum(r.score for r in members)
        total_max = sum(r.max_score for r in members)
        for row in members:
            rest_max = total_max - row.max_score
            if rest_max > 0:
                pairs[row.question_id].append((row.fraction, (total - row.score) / rest_max))
    return pairs


def compute_stats(rows: Sequence[AttemptRow]) -> dict[str, ItemStat]:
    fractions: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        fractions[row.question_id].append(row.fraction)
    pairs = rest_pairs(rows)
    stats: dict[str, ItemStat] = {}
    for question_id, values in fractions.items():
        exam_pairs = pairs.get(question_id, [])
        stats[question_id] = ItemStat(
            question_id=question_id,
            attempts=len(values),
            correct=sum(1 for v in values if v >= 1.0),
            p_value=facility(values),
            discrimination=point_biserial([p[0] for p in exam_pairs], [p[1] for p in exam_pairs]),
            discrimination_n=len(exam_pairs),
        )
    return stats


def retirement_reason(stat: ItemStat) -> str | None:
    """A stable reason code when the item must retire, else None."""
    if stat.attempts < MIN_ATTEMPTS or stat.p_value is None:
        return None
    if stat.p_value > FACILITY_MAX:
        return "facility_too_high"
    if stat.p_value < FACILITY_MIN:
        return "facility_too_low"
    judged = stat.discrimination_n >= MIN_DISCRIMINATION_SAMPLE
    if judged and (stat.discrimination is None or stat.discrimination < MIN_DISCRIMINATION):
        return "discrimination_too_low"
    return None


def decision(stat: ItemStat) -> str:
    if stat.attempts < MIN_ATTEMPTS:
        return "insufficient"
    return "retire" if retirement_reason(stat) else "keep"
