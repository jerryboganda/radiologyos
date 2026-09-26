"""Per-topic mastery, spec section 7: m = 0.5 a + 0.3 r + 0.2 k.

* ``a`` exponentially weighted accuracy, half-life 14 days, blending question
  attempts (fractional score, counted ``QUESTION_WEIGHT`` times) with card
  reviews (rating >= 2 is correct, counted once): a graded exam item is a
  stronger signal of exam performance than a self-rated flashcard;
* ``r`` mean FSRS retrievability of the topic's cards;
* ``k`` coverage, the fraction of the topic's material (cards plus active
  questions) studied at least once (a card reviewed, a question attempted).

Bands: weak < 0.5, learning 0.5-0.8, mastered >= 0.8. Self-rated confidence is
never folded in, and no pass probability is derived from mastery.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

HALF_LIFE_DAYS = 14.0
QUESTION_WEIGHT = 2.0
REVIEW_WEIGHT = 1.0

Band = Literal["weak", "learning", "mastered"]


@dataclass(frozen=True, slots=True)
class Attempt:
    """One accuracy observation; ``correct`` may be fractional (partial marks)."""

    age_days: float
    correct: bool | float
    weight: float = REVIEW_WEIGHT


def review_attempt(age_days: float, rating: int) -> Attempt:
    return Attempt(age_days, rating >= 2, REVIEW_WEIGHT)


def question_attempt(age_days: float, score: float, max_score: float) -> Attempt:
    ratio = min(max(score / max_score, 0.0), 1.0) if max_score > 0 else 0.0
    return Attempt(age_days, ratio, QUESTION_WEIGHT)


def coverage_share(
    cards: int, cards_reviewed: int, questions: int, questions_attempted: int
) -> float:
    """Share of a topic's cards and active questions touched at least once."""
    total = max(cards, 0) + max(questions, 0)
    if total == 0:
        return 0.0
    done = min(max(cards_reviewed, 0), max(cards, 0))
    done += min(max(questions_attempted, 0), max(questions, 0))
    return done / total


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
        weight = max(attempt.weight, 0.0) * 0.5 ** (max(attempt.age_days, 0.0) / half_life)
        total += weight
        right += weight * min(max(float(attempt.correct), 0.0), 1.0)
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
