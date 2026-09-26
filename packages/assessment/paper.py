"""Assemble a mock paper from a blueprint's counts and per-system mix (pure, ADR 0023).

For each item type the requested count is split across the mix groups by
largest remainder; each group draws random questions whose resolved system is
in the group, preferring questions generated for the blueprint's exam. What a
group cannot supply is filled from any other question of that type, and what
the bank cannot supply at all is reported as ``shortfall`` rather than hidden.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from packages.assessment.blueprints import MixGroup, largest_remainder


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    question_id: UUID
    item_type: str
    system: str | None
    tagged: bool


def _take(
    pool: Sequence[PaperCandidate], fits: Callable[[PaperCandidate], bool], want: int,
    used: set[UUID],
) -> list[PaperCandidate]:
    taken: list[PaperCandidate] = []
    for candidate in pool:
        if len(taken) >= want:
            break
        if candidate.question_id not in used and fits(candidate):
            used.add(candidate.question_id)
            taken.append(candidate)
    return taken


def _in(systems: Sequence[str]) -> Callable[[PaperCandidate], bool]:
    wanted = frozenset(systems)
    return lambda candidate: candidate.system in wanted


def assemble(
    candidates: Sequence[PaperCandidate], counts: Mapping[str, int],
    groups: Sequence[MixGroup], seed: int,
) -> tuple[list[tuple[UUID, str]], dict[str, Any]]:
    """Return the picked (question id, type) pairs and a mix report."""
    rng = random.Random(seed)  # nosec B311 - paper shuffling, not security
    pool = list(candidates)
    rng.shuffle(pool)
    pool.sort(key=lambda c: not c.tagged)  # stable: tagged first, random within
    used: set[UUID] = set()
    picks: list[tuple[UUID, str]] = []
    report_groups: list[dict[str, Any]] = [
        {"label": g.label, "systems": list(g.systems), "requested": 0, "picked": 0}
        for g in groups
    ]
    types: dict[str, dict[str, int]] = {}
    outside = 0
    for item_type, wanted in counts.items():
        of_type = [c for c in pool if c.item_type == item_type]
        chosen: list[PaperCandidate] = []
        for index, want in enumerate(largest_remainder(wanted, [g.share for g in groups])):
            got = _take(of_type, _in(groups[index].systems), want, used)
            report_groups[index]["requested"] += want
            report_groups[index]["picked"] += len(got)
            chosen.extend(got)
        fill = _take(of_type, lambda c: True, wanted - len(chosen), used)
        outside += len(fill)
        chosen.extend(fill)
        rng.shuffle(chosen)
        picks.extend((c.question_id, c.item_type) for c in chosen)
        types[item_type] = {"requested": wanted, "picked": len(chosen)}
    requested = sum(counts.values())
    report = {"types": types, "groups": report_groups, "filled_outside_mix": outside,
              "shortfall": requested - len(picks)}
    return picks, report
