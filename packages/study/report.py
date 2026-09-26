"""Weekly study report, computed in code (no model call, no pass probability).

Minutes studied are estimated from review and attempt timestamps: events are
ordered, a gap of at most ``IDLE_CAP_MINUTES`` counts in full, and each event
that starts a session (the first, or one after a longer gap) counts
``SESSION_START_MINUTES``. Retention achieved is the FSRS "true retention":
the share of reviews of cards in the ``review`` state rated Hard or better,
compared with the phase's target. Weakest systems are the lowest-mastery
systems that have material; next-week focus is the planner's top priorities.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

REPORT_VERSION = 1
IDLE_CAP_MINUTES = 5.0
SESSION_START_MINUTES = 1.0
TOP_N = 3


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    at: datetime
    rating: int
    state_before: str


@dataclass(frozen=True, slots=True)
class AttemptEvent:
    at: datetime
    score: float
    max_score: float


@dataclass(frozen=True, slots=True)
class SystemStatus:
    code: str
    title: str
    mastery: float
    band: str
    priority: float
    has_material: bool
    recent_lapse: bool = False
    started: bool = True


@dataclass(frozen=True, slots=True)
class WeekInputs:
    week_start: date
    zone: tzinfo
    reviews: Sequence[ReviewEvent]
    attempts: Sequence[AttemptEvent]
    systems: Sequence[SystemStatus]
    target_retention: float
    planned_minutes: int
    days_remaining: int
    phase: str
    weight_policy: str


def daily_minutes(times: Sequence[datetime], week_start: date, zone: tzinfo) -> list[float]:
    """Estimated study minutes per local day of the week starting ``week_start``."""
    days = [0.0] * 7
    previous: datetime | None = None
    for at in sorted(times):
        gap = None if previous is None else (at - previous).total_seconds() / 60
        minutes = gap if gap is not None and gap <= IDLE_CAP_MINUTES else SESSION_START_MINUTES
        index = (at.astimezone(zone).date() - week_start).days
        if 0 <= index < 7:
            days[index] += minutes
        previous = at
    return days


def retention_achieved(reviews: Sequence[ReviewEvent]) -> tuple[float | None, int]:
    eligible = [r for r in reviews if r.state_before == "review"]
    if not eligible:
        return None, 0
    return round(sum(r.rating >= 2 for r in eligible) / len(eligible), 4), len(eligible)


def _reason(system: SystemStatus) -> str:
    if system.recent_lapse:
        return "recent lapses"
    if not system.started:
        return "not started"
    if system.band == "weak":
        return "weak mastery"
    return "highest priority"


def weakest(systems: Sequence[SystemStatus]) -> list[dict[str, Any]]:
    ranked = sorted((s for s in systems if s.has_material),
                    key=lambda s: (s.mastery, -s.priority, s.code))
    return [{"code": s.code, "title": s.title, "mastery": s.mastery, "band": s.band}
            for s in ranked[:TOP_N]]


def focus(systems: Sequence[SystemStatus]) -> list[dict[str, Any]]:
    ranked = sorted(systems, key=lambda s: (-s.priority, s.code))
    return [{"code": s.code, "title": s.title, "reason": _reason(s)} for s in ranked[:TOP_N]]


def _notes(inputs: WeekInputs, minutes: int, achieved: float | None) -> list[str]:
    notes: list[str] = []
    if inputs.planned_minutes and minutes < 0.8 * inputs.planned_minutes:
        notes.append(f"Studied about {minutes} of {inputs.planned_minutes} planned minutes.")
    if achieved is not None and achieved < inputs.target_retention:
        notes.append(f"Retention {achieved:.0%} is below the {inputs.target_retention:.0%} "
                     "target: clear due reviews before new cards.")
    if not inputs.attempts:
        notes.append("No questions attempted: the test block builds exam accuracy.")
    if inputs.weight_policy != "past_paper_approved":
        notes.append("Systems are weighted equally until you approve past-paper weights.")
    return notes


def build_report(inputs: WeekInputs) -> dict[str, Any]:
    """JSON-ready weekly report for the local week starting ``inputs.week_start``."""
    times = [r.at for r in inputs.reviews] + [a.at for a in inputs.attempts]
    per_day = daily_minutes(times, inputs.week_start, inputs.zone)
    minutes = round(sum(per_day))
    achieved, eligible = retention_achieved(inputs.reviews)
    scored = sum(a.max_score for a in inputs.attempts)
    accuracy = round(sum(a.score for a in inputs.attempts) / scored, 4) if scored else None
    return {
        "report_version": REPORT_VERSION,
        "week_start": inputs.week_start.isoformat(),
        "week_end": (inputs.week_start + timedelta(days=6)).isoformat(),
        "minutes_studied": minutes,
        "planned_minutes": inputs.planned_minutes,
        "daily_minutes": [round(m) for m in per_day],
        "active_days": sum(1 for m in per_day if m > 0),
        "reviews": len(inputs.reviews),
        "questions": len(inputs.attempts),
        "question_accuracy": accuracy,
        "retention": {"achieved": achieved, "target": inputs.target_retention,
                      "eligible_reviews": eligible,
                      "met": None if achieved is None else achieved >= inputs.target_retention},
        "weakest": weakest(inputs.systems),
        "focus": focus(inputs.systems),
        "notes": _notes(inputs, minutes, achieved),
        "days_remaining": inputs.days_remaining,
        "phase": inputs.phase,
        "weight_policy": inputs.weight_policy,
    }
