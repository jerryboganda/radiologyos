"""Per-topic mastery, spec section 7: m = 0.5 a + 0.3 r + 0.2 k.

* ``a`` exponentially weighted accuracy of attempts, half-life 14 days;
* ``r`` mean FSRS retrievability of the topic's cards;
* ``k`` coverage, the fraction of the topic's material studied at least once.

Bands: weak < 0.5, learning 0.5-0.8, mastered >= 0.8. Self-rated confidence is
never folded in, and no pass probability is derived from mastery.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

HALF_LIFE_DAYS = 14.0

Band = Literal["weak", "learning", "mastered"]


@dataclass(frozen=True, slots=True)
class Attempt:
    age_days: float
    correct: bool


@dataclass(frozen=True, slots=True)
class Mastery:
    score: float
    accuracy: float
    retrievability: float
    coverage: float
    band: Band


def weighted_accuracy(attempts: Iterable[Attempt], half_life: float = HALF_LIFE_DAYS) -> float:
    total = 0.0
    right = 0.0
    for attempt in attempts:
        weight = 0.5 ** (max(attempt.age_days, 0.0) / half_life)
        total += weight
        right += weight * attempt.correct
    return right / total if total else 0.0


def band_for(score: float) -> Band:
    if score >= 0.8:
        return "mastered"
    if score >= 0.5:
        return "learning"
    return "weak"


def mastery(
    attempts: Sequence[Attempt], retrievabilities: Sequence[float], coverage: float
) -> Mastery:
    a = weighted_accuracy(attempts)
    r = sum(retrievabilities) / len(retrievabilities) if retrievabilities else 0.0
    k = min(max(coverage, 0.0), 1.0)
    score = min(max(0.5 * a + 0.3 * r + 0.2 * k, 0.0), 1.0)
    return Mastery(round(score, 4), round(a, 4), round(r, 4), round(k, 4), band_for(score))
