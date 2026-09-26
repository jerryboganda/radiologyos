"""FSRS-5 spaced-repetition scheduler, implemented from the published algorithm.

Source: open-spaced-repetition, "The Algorithm" (FSRS-5), fsrs4anki wiki,
https://github.com/open-spaced-repetition/fsrs4anki/wiki/The-Algorithm, and the
reference implementation py-fsrs (DEFAULT_PARAMETERS for FSRS-5). Formulas:

* retrievability  R(t, S) = (1 + F * t / S) ** DECAY, DECAY = -0.5, F = 19/81,
  so R(S, S) = 0.9 (FSRS-4 used the simpler (1 + t / (9 S)) ** -1);
* interval        I(r, S) = S / F * (r ** (1 / DECAY) - 1), so I(0.9, S) = S;
* initial         S0(G) = w[G-1];  D0(G) = w4 - exp(w5 * (G - 1)) + 1;
* difficulty      D' = D + (-w6 * (G - 3)) * (10 - D) / 9 (linear damping), then
  mean reversion D'' = w7 * D0(4) + (1 - w7) * D', clamped to [1, 10];
* recall          S' = S * (exp(w8) * (11 - D) * S ** -w9 * (exp(w10 * (1 - R)) - 1)
  * (w15 if Hard) * (w16 if Easy) + 1);
* lapse           S' = min(w11 * D ** -w12 * ((S + 1) ** w13 - 1) * exp(w14 * (1 - R)), S);
* same day        S' = S * exp(w17 * (G - 3 + w18)).

There are no learning steps: a lapse (Again) is re-shown after ``RELEARN_DELAY``
and every pass schedules at least one day ahead. The spec names py-fsrs; it is
implemented here instead to avoid a new dependency (ADR 0014).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Literal

DEFAULT_W: tuple[float, ...] = (
    0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575,
    0.1192, 1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621,
)
DECAY = -0.5
FACTOR = 19 / 81
DESIRED_RETENTION = 0.90
FINAL_MONTH_RETENTION = 0.93
MAX_INTERVAL_DAYS = 36500
RELEARN_DELAY = timedelta(minutes=10)
MIN_STABILITY = 0.01

CardState = Literal["new", "learning", "review", "relearning"]


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass(frozen=True, slots=True)
class CardMemory:
    """The scheduling state stored on each card row."""

    state: CardState = "new"
    stability: float = 0.0
    difficulty: float = 0.0
    due_at: datetime | None = None
    last_review_at: datetime | None = None
    reps: int = 0
    lapses: int = 0


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    card: CardMemory
    elapsed_days: int
    scheduled_days: int
    retrievability: float | None


def retrievability(elapsed_days: float, stability: float) -> float:
    """Probability of recall after ``elapsed_days`` for memory stability ``stability``."""
    if stability <= 0:
        return 0.0
    return float((1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY)


def next_interval(stability: float, retention: float = DESIRED_RETENTION) -> int:
    """Whole days until recall probability falls to ``retention`` (at least 1)."""
    if not 0.5 <= retention < 1:
        raise ValueError("desired retention must be in [0.5, 1)")
    days = stability / FACTOR * (retention ** (1 / DECAY) - 1)
    return int(min(max(round(days), 1), MAX_INTERVAL_DAYS))


def retention_for(days_remaining: int | None) -> float:
    """Spec section 7: 0.90, raised to 0.93 in the last 30 days before the exam."""
    if days_remaining is not None and days_remaining <= 30:
        return FINAL_MONTH_RETENTION
    return DESIRED_RETENTION


def _clamp_d(value: float) -> float:
    return min(max(value, 1.0), 10.0)


def initial_difficulty(rating: Rating, w: tuple[float, ...] = DEFAULT_W) -> float:
    return _clamp_d(w[4] - math.exp(w[5] * (int(rating) - 1)) + 1)


def next_difficulty(d: float, rating: Rating, w: tuple[float, ...] = DEFAULT_W) -> float:
    delta = -w[6] * (int(rating) - 3)
    damped = d + delta * (10 - d) / 9
    reverted = w[7] * initial_difficulty(Rating.EASY, w) + (1 - w[7]) * damped
    return _clamp_d(reverted)


def recall_stability(
    d: float, s: float, r: float, rating: Rating, w: tuple[float, ...] = DEFAULT_W
) -> float:
    hard = w[15] if rating == Rating.HARD else 1.0
    easy = w[16] if rating == Rating.EASY else 1.0
    growth = math.exp(w[8]) * (11 - d) * math.pow(s, -w[9]) * (math.exp(w[10] * (1 - r)) - 1)
    return s * (growth * hard * easy + 1)


def lapse_stability(d: float, s: float, r: float, w: tuple[float, ...] = DEFAULT_W) -> float:
    forgotten = (w[11] * math.pow(d, -w[12]) * (math.pow(s + 1, w[13]) - 1)
                 * math.exp(w[14] * (1 - r)))
    return min(forgotten, s)


def short_term_stability(s: float, rating: Rating, w: tuple[float, ...] = DEFAULT_W) -> float:
    return s * math.exp(w[17] * (int(rating) - 3 + w[18]))


def _memory_update(
    card: CardMemory, rating: Rating, elapsed: int, w: tuple[float, ...]
) -> tuple[float, float, float | None]:
    """Return (stability, difficulty, retrievability-at-review) after a rating."""
    if card.state == "new" or card.last_review_at is None:
        return w[int(rating) - 1], initial_difficulty(rating, w), None
    if elapsed < 1:
        return (short_term_stability(card.stability, rating, w),
                next_difficulty(card.difficulty, rating, w), None)
    r = retrievability(elapsed, card.stability)
    if rating == Rating.AGAIN:
        s = lapse_stability(card.difficulty, card.stability, r, w)
    else:
        s = recall_stability(card.difficulty, card.stability, r, rating, w)
    return s, next_difficulty(card.difficulty, rating, w), r


def review(
    card: CardMemory,
    rating: Rating | int,
    now: datetime,
    retention: float = DESIRED_RETENTION,
    w: tuple[float, ...] = DEFAULT_W,
) -> ReviewOutcome:
    """Apply one review to ``card`` at ``now`` and return the rescheduled card."""
    rating = Rating(int(rating))
    if card.last_review_at is not None and now < card.last_review_at:
        raise ValueError("review time precedes the last review")
    elapsed = 0 if card.last_review_at is None else (now - card.last_review_at).days
    stability, difficulty, r = _memory_update(card, rating, elapsed, w)
    stability = max(stability, MIN_STABILITY)
    lapsed = rating == Rating.AGAIN and card.state == "review"
    if rating == Rating.AGAIN:
        state: CardState = "learning" if card.state in ("new", "learning") else "relearning"
        scheduled, due = 0, now + RELEARN_DELAY
    else:
        state = "review"
        scheduled = next_interval(stability, retention)
        due = now + timedelta(days=scheduled)
    updated = replace(
        card, state=state, stability=stability, difficulty=difficulty, due_at=due,
        last_review_at=now, reps=card.reps + 1, lapses=card.lapses + int(lapsed),
    )
    return ReviewOutcome(updated, elapsed, scheduled, r)


def current_retrievability(card: CardMemory, now: datetime) -> float:
    """R of a card at ``now``; a never-reviewed card has nothing to retrieve (0)."""
    if card.last_review_at is None or card.stability <= 0:
        return 0.0
    elapsed = (now - card.last_review_at).total_seconds() / 86400
    return retrievability(elapsed, card.stability)
