"""Baseline diagnostic: a short timed SBA test spread across curriculum systems.

Selection is round-robin over systems (each system's questions shuffled), so
the test samples as many systems as the question bank allows before any system
gets a second item. Results are summarised per system from the graded exam
items; the graded attempts themselves feed mastery accuracy.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

BASELINE_SIZE = 20
BASELINE_MIN = 8
MINUTES_PER_ITEM = 1.5


@dataclass(frozen=True, slots=True)
class Candidate:
    question_id: UUID
    curriculum_code: str


def time_limit_minutes(count: int) -> int:
    return max(int(round(count * MINUTES_PER_ITEM)), 1)


def pick(candidates: Sequence[Candidate], size: int, seed: int) -> list[Candidate]:
    """Up to ``size`` questions, round-robin across systems in a seeded random order."""
    rng = random.Random(seed)  # nosec B311 - question order, not a security decision
    pools: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in sorted(candidates, key=lambda c: (c.curriculum_code, str(c.question_id))):
        pools[candidate.curriculum_code].append(candidate)
    for pool in pools.values():
        rng.shuffle(pool)
    order = sorted(pools)
    rng.shuffle(order)
    chosen: list[Candidate] = []
    while len(chosen) < size and any(pools[code] for code in order):
        for code in order:
            if pools[code] and len(chosen) < size:
                chosen.append(pools[code].pop())
    return chosen


def per_system(
    items: Sequence[Mapping[str, Any]], systems: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Per-system correct/total/accuracy from graded exam items."""
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0, "correct": 0.0})
    for item in items:
        code = systems.get(str(item["question_id"]))
        if code is None:
            continue
        maximum = float(item.get("max_score") or 1.0)
        totals[code]["total"] += 1
        totals[code]["correct"] += float(item.get("score") or 0.0) / maximum
    return [
        {"code": code, "questions": int(t["total"]), "correct": round(t["correct"], 2),
         "accuracy": round(t["correct"] / t["total"], 4) if t["total"] else 0.0}
        for code, t in sorted(totals.items())
    ]
