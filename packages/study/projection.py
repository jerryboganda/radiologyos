"""Days-remaining projection (spec section 7, "Signals to the student").

Weighted coverage is ``sum(w_i * k_i)`` over curriculum nodes (weights sum to 1,
``k`` as in mastery). Each completed Today session freezes the weighted coverage
at that moment, so the pace is measured, not assumed: over the recent window,
coverage gained per day and per study minute. From that pace the projection
gives the coverage expected on exam day, and the minutes per day needed to reach
``COVERAGE_GOAL`` by ``BUFFER_DAYS`` before the exam (the spec's "finish
coverage 30 days before the exam"). It is a study-pace estimate, never a pass
probability, and it says "insufficient history" rather than guess.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

WINDOW_DAYS = 28
MIN_SPAN_DAYS = 3
BUFFER_DAYS = 30
COVERAGE_GOAL = 0.9

Status = Literal["insufficient_history", "on_track", "behind", "done"]


@dataclass(frozen=True, slots=True)
class PacePoint:
    """One completed session: its local date, frozen weighted coverage, minutes."""

    day: date
    coverage: float
    minutes: int


@dataclass(frozen=True, slots=True)
class Topic:
    weight: float
    coverage: float


def weighted_coverage(topics: Sequence[Topic]) -> float:
    total = sum(max(t.weight, 0.0) for t in topics)
    if total <= 0:
        return 0.0
    covered = sum(max(t.weight, 0.0) * min(max(t.coverage, 0.0), 1.0) for t in topics)
    return covered / total


def _window(history: Sequence[PacePoint], today: date) -> list[PacePoint]:
    recent = [p for p in history if 0 <= (today - p.day).days <= WINDOW_DAYS]
    return sorted(recent, key=lambda p: p.day)


def _pace(window: list[PacePoint], today: date,
          coverage_now: float) -> tuple[float, float, float | None] | None:
    """(coverage per day, minutes per day, coverage per minute), or None if too little."""
    if not window:
        return None
    span = (today - window[0].day).days
    if span < MIN_SPAN_DAYS:
        return None
    gain = max(coverage_now - window[0].coverage, 0.0)
    minutes = sum(p.minutes for p in window[1:])
    per_minute = gain / minutes if minutes > 0 and gain > 0 else None
    return gain / span, minutes / span, per_minute


def _needed(remaining: float, per_minute: float | None, days: int) -> float | None:
    if remaining <= 0:
        return 0.0
    if per_minute is None or days <= 0:
        return None
    return remaining / per_minute / days


def project(
    today: date, exam_date: date, topics: Sequence[Topic], history: Sequence[PacePoint],
) -> dict[str, Any]:
    """JSON-ready projection; numbers are ``None`` while the history is too short."""
    days_left = max((exam_date - today).days, 0)
    to_target = max(days_left - BUFFER_DAYS, 0) or days_left
    now = weighted_coverage(topics)
    remaining = max(COVERAGE_GOAL - now, 0.0)
    left = [t for t in topics if t.weight > 0 and t.coverage < COVERAGE_GOAL]
    pace = _pace(_window(history, today), today, now)
    out: dict[str, Any] = {
        "days_remaining": days_left, "target_days": to_target, "goal": COVERAGE_GOAL,
        "coverage": round(now, 4),
        "remaining_weighted": round(sum(t.weight * (1 - min(t.coverage, 1.0)) for t in left)
                                    / (sum(t.weight for t in topics) or 1.0), 4),
        "topics_remaining": len(left), "sessions_in_window": len(_window(history, today)),
        "coverage_per_day": None, "minutes_per_day": None, "projected_coverage": None,
        "needed_minutes_per_day": None, "needed_hours_per_day": None,
    }
    if remaining <= 0:
        return {**out, "status": "done", "needed_minutes_per_day": 0.0,
                "needed_hours_per_day": 0.0}
    if pace is None:
        return {**out, "status": "insufficient_history"}
    per_day, minutes_per_day, per_minute = pace
    needed = _needed(remaining, per_minute, to_target)
    at_target = now + per_day * to_target
    return {
        **out,
        "status": "on_track" if at_target >= COVERAGE_GOAL else "behind",
        "coverage_per_day": round(per_day, 5),
        "minutes_per_day": round(minutes_per_day, 1),
        "projected_coverage": round(min(now + per_day * days_left, 1.0), 4),
        "needed_minutes_per_day": None if needed is None else round(needed, 1),
        "needed_hours_per_day": None if needed is None else round(needed / 60, 1),
    }
