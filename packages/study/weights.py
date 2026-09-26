"""Map owner-approved past-paper topic weights onto curriculum systems (ADR 0014, 0016).

Only system-level rows (``topic == ''``) that the owner approved are used. For
the profile's exam targets that have approved rows, each target's weights are
completed (a system the owner left unapproved gets that target's smallest
approved weight, a conservative prior), normalised to sum to 1, averaged across
targets, and normalised again. When no profile target has approved rows, the
approved ``all`` aggregate is used; when that is missing too, every system gets
the same weight (``equal_unvalidated``). The planner's ``w`` is therefore on the
same scale in every case: weights sum to 1 over the curriculum systems.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

WeightPolicy = Literal["past_paper_approved", "equal_unvalidated"]
ALL_TARGETS = "all"


@dataclass(frozen=True, slots=True)
class ApprovedWeight:
    exam_target: str
    curriculum_code: str
    weight: float


@dataclass(frozen=True, slots=True)
class WeightMap:
    policy: WeightPolicy
    targets: tuple[str, ...]
    weights: dict[str, float]

    def weight_for(self, code: str) -> float:
        return self.weights.get(code, 0.0)


def equal_weights(systems: Sequence[str]) -> WeightMap:
    share = 1.0 / len(systems) if systems else 0.0
    return WeightMap("equal_unvalidated", (), {code: share for code in systems})


def _normalise(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        return {code: 1.0 / len(values) for code in values} if values else {}
    return {code: value / total for code, value in values.items()}


def _target_vector(rows: Sequence[ApprovedWeight], systems: Sequence[str]) -> dict[str, float]:
    given = {row.curriculum_code: max(row.weight, 0.0) for row in rows}
    floor = min(given.values())
    return _normalise({code: given.get(code, floor) for code in systems})


def map_weights(
    rows: Iterable[ApprovedWeight], exam_targets: Sequence[str], systems: Sequence[str]
) -> WeightMap:
    """Planner weights per curriculum system from approved system-level rows."""
    known = set(systems)
    by_target: dict[str, list[ApprovedWeight]] = defaultdict(list)
    for row in rows:
        if row.curriculum_code in known:
            by_target[row.exam_target].append(row)
    used = tuple(t for t in dict.fromkeys(exam_targets) if by_target.get(t))
    if not used and by_target.get(ALL_TARGETS):
        used = (ALL_TARGETS,)
    if not used or not systems:
        return equal_weights(systems)
    vectors = [_target_vector(by_target[target], systems) for target in used]
    mean = {code: sum(v[code] for v in vectors) / len(vectors) for code in systems}
    rounded = {code: round(value, 6) for code, value in _normalise(mean).items()}
    return WeightMap("past_paper_approved", used, rounded)
