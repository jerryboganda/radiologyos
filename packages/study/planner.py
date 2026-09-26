"""Exam-date-first daily planner, spec section 7. Rules-based and deterministic.

Priority per curriculum node: p = w * (1 - m) * (1 + 0.5 c) * d, where ``w`` is
the exam weight (owner-approved past-paper weights mapped onto systems by
``packages.study.weights``, else equal weights), ``m`` the
mastery, ``c`` 1 for open conflicts or recent lapses, and ``d`` a recency decay
rising from 1 to 2 over 30 untouched days. The session mix and rules come from
the phase implied by days remaining. No model is called and no pass
probability is computed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from packages.study.fsrs import retention_for
from packages.study.mastery import band_for

PLANNER_VERSION = 2
REVIEW_CARDS_PER_MINUTE = 3
MINUTES_PER_QUESTION = 1.5
MINUTES_PER_IMAGE_PROMPT = 5
NEW_CARD_CAP = 25
DECAY_HORIZON_DAYS = 30
BLOCKS = ("learn", "review", "test", "viva")

Phase = Literal["coverage", "coverage_consolidation", "consolidation", "exam_mode", "taper"]
MIX: dict[Phase, tuple[int, int, int, int]] = {  # learn / review / test / viva, percent
    "coverage": (55, 15, 25, 5),
    "coverage_consolidation": (40, 20, 30, 10),
    "consolidation": (20, 25, 40, 15),
    "exam_mode": (10, 25, 45, 20),
    "taper": (0, 40, 40, 20),
}
LEARN_TOPICS: dict[Phase, int] = {
    "coverage": 1, "coverage_consolidation": 2, "consolidation": 3, "exam_mode": 2, "taper": 0,
}
RULES: dict[Phase, str] = {
    "coverage": "New topics in priority order; finish one system before the next.",
    "coverage_consolidation": "Interleave two systems; keep reviews daily.",
    "consolidation": "Weekly mock paper; weak topics get double learning slots.",
    "exam_mode": "Two mock papers a week; a TOACS-style image set every day.",
    "taper": "No new material; rapid revision and high-yield cards only.",
}


def phase_for(days_remaining: int) -> Phase:
    if days_remaining > 180:
        return "coverage"
    if days_remaining >= 90:
        return "coverage_consolidation"
    if days_remaining >= 30:
        return "consolidation"
    if days_remaining >= 7:
        return "exam_mode"
    return "taper"


@dataclass(frozen=True, slots=True)
class TopicSignal:
    code: str
    title: str
    mastery: float = 0.0
    weight: float | None = None
    recent_lapse: bool = False
    conflict: bool = False
    days_untouched: int | None = None


@dataclass(frozen=True, slots=True)
class RankedTopic:
    code: str
    title: str
    priority: float
    mastery: float
    band: str


def recency_decay(days_untouched: int | None) -> float:
    if days_untouched is None:
        return 2.0
    return 1.0 + min(max(days_untouched, 0), DECAY_HORIZON_DAYS) / DECAY_HORIZON_DAYS


def priority(signal: TopicSignal, default_weight: float) -> float:
    weight = default_weight if signal.weight is None else signal.weight
    c = 1.0 if signal.recent_lapse or signal.conflict else 0.0
    m = min(max(signal.mastery, 0.0), 1.0)
    return weight * (1 - m) * (1 + 0.5 * c) * recency_decay(signal.days_untouched)


def rank_topics(signals: Sequence[TopicSignal]) -> list[RankedTopic]:
    default_weight = 1.0 / len(signals) if signals else 0.0
    ranked = [
        RankedTopic(s.code, s.title, round(priority(s, default_weight), 6), s.mastery,
                    band_for(s.mastery))
        for s in signals
    ]
    return sorted(ranked, key=lambda t: (-t.priority, t.code))


def _largest_remainder(total: int, parts: Sequence[float]) -> list[int]:
    """Split ``total`` into integers proportional to ``parts``, summing exactly."""
    weight = sum(parts)
    if total <= 0 or weight <= 0:
        return [0 for _ in parts]
    raw = [total * p / weight for p in parts]
    out = [math.floor(x) for x in raw]
    order = sorted(range(len(parts)), key=lambda i: (-(raw[i] - out[i]), i))
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def allocate_minutes(minutes: int, phase: Phase, due_count: int) -> dict[str, int]:
    """Minutes per block; always sums to ``minutes`` exactly.

    Review time shrinks to what the due cards need (surplus goes to learning, or
    to testing when the phase has no new learning) and may borrow up to half of
    the learning time when many cards are due.
    """
    alloc = dict(zip(BLOCKS, _largest_remainder(max(minutes, 0), MIX[phase]), strict=True))
    need = math.ceil(max(due_count, 0) / REVIEW_CARDS_PER_MINUTE)
    if need < alloc["review"]:
        surplus = alloc["review"] - need
        alloc["review"] = need
        alloc["learn" if MIX[phase][0] else "test"] += surplus
    elif need > alloc["review"]:
        borrow = min(need - alloc["review"], alloc["learn"] // 2)
        alloc["review"] += borrow
        alloc["learn"] -= borrow
    return alloc


@dataclass(frozen=True, slots=True)
class DayInputs:
    today: date
    exam_date: date
    minutes: int
    due_count: int
    new_available: int
    topics: Sequence[TopicSignal]
    exam_targets: Sequence[str] = field(default_factory=tuple)
    weight_policy: str = "equal_unvalidated"
    weight_targets: Sequence[str] = field(default_factory=tuple)


def _learn_block(phase: Phase, minutes: int, ranked: list[RankedTopic],
                 new_available: int) -> dict[str, Any]:
    chosen = ranked[: LEARN_TOPICS[phase]] if minutes else []
    slots = [2 if phase == "consolidation" and t.band == "weak" else 1 for t in chosen]
    split = _largest_remainder(minutes, slots)
    return {
        "kind": "learn", "minutes": minutes,
        "new_cards": min(NEW_CARD_CAP, max(new_available, 0), minutes),
        "topics": [{"code": t.code, "title": t.title, "minutes": m, "slots": s}
                   for t, m, s in zip(chosen, split, slots, strict=True)],
    }


def _test_block(phase: Phase, minutes: int, today: date, focus: list[str],
                ranked: list[RankedTopic]) -> dict[str, Any]:
    questions = max(round(minutes / MINUTES_PER_QUESTION), 1)
    from_today = round(questions * 0.6)
    weak = [t.code for t in ranked if t.code not in focus][:3]
    mock_days = {"consolidation": (5,), "exam_mode": (2, 5)}.get(phase, ())
    return {
        "kind": "test", "minutes": minutes, "questions": questions,
        "from_today_topics": from_today, "interleaved_weak": questions - from_today,
        "topics": focus, "weak_topics": weak,
        "mock_paper_suggested": today.weekday() in mock_days,
    }


def build_plan(inputs: DayInputs) -> dict[str, Any]:
    """One day's plan as JSON-ready data; block minutes sum to ``inputs.minutes``."""
    days_remaining = max((inputs.exam_date - inputs.today).days, 0)
    phase = phase_for(days_remaining)
    ranked = rank_topics(inputs.topics)
    alloc = allocate_minutes(inputs.minutes, phase, inputs.due_count)
    learn = _learn_block(phase, alloc["learn"], ranked, inputs.new_available)
    focus = [t["code"] for t in learn["topics"]] or [t.code for t in ranked[:2]]
    blocks: list[dict[str, Any]] = [
        {"kind": "review", "minutes": alloc["review"], "due_cards": inputs.due_count,
         "target_cards": min(inputs.due_count, alloc["review"] * REVIEW_CARDS_PER_MINUTE)},
        learn,
        _test_block(phase, alloc["test"], inputs.today, focus, ranked),
        {"kind": "viva", "minutes": alloc["viva"], "topics": focus,
         "format": "toacs_image_set" if phase == "exam_mode" else "image_prompt",
         "image_prompts": max(alloc["viva"] // MINUTES_PER_IMAGE_PROMPT, 1)},
    ]
    return {
        "plan_version": PLANNER_VERSION,
        "plan_date": inputs.today.isoformat(),
        "exam_date": inputs.exam_date.isoformat(),
        "days_remaining": days_remaining,
        "phase": phase,
        "rule": RULES[phase],
        "minutes": inputs.minutes,
        "retention": retention_for(days_remaining),
        "exam_targets": list(inputs.exam_targets),
        "weight_policy": inputs.weight_policy,
        "weight_targets": list(inputs.weight_targets),
        "blocks": [b for b in blocks if b["minutes"] > 0],
        "priorities": [
            {"code": t.code, "title": t.title, "priority": t.priority,
             "mastery": t.mastery, "band": t.band}
            for t in ranked[:10]
        ],
    }
