"""Past-paper topic weights: smoothed normalised frequency per exam target.

For each exam target (and the aggregate ``all``), with N questions observed:

* system level (``topic == ''``): every curriculum system c gets
  ``(n_c + alpha) / (N + alpha * K)`` over the K systems in the pack, so
  systems never asked still receive a small, explicit prior weight and the
  weights sum to 1;
* topic level: every observed (system, topic) pair gets
  ``(n_t + alpha) / (N + alpha * T)`` over the T observed topics.

Weights are suggestions: they are stored unapproved and only the owner's
approval makes them usable (ADR 0011, ADR 0016). ``basis`` records the counts,
paper coverage, and years so the owner can see why a weight is what it is.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

METHOD = "laplace_v1"
ALPHA = 1.0
ALL = "all"


@dataclass(frozen=True, slots=True)
class Observation:
    exam_target: str
    curriculum_code: str
    topic: str
    paper_key: str
    year: int | None
    count: int


@dataclass(frozen=True, slots=True)
class Weight:
    exam_target: str
    curriculum_code: str
    topic: str
    weight: float
    basis: dict[str, Any]


def _basis(
    rows: Sequence[Observation], total: int, total_papers: int, categories: int, alpha: float
) -> dict[str, Any]:
    years = sorted({r.year for r in rows if r.year is not None})
    return {
        "method": METHOD, "alpha": alpha, "count": sum(r.count for r in rows),
        "total": total, "categories": categories,
        "papers": len({r.paper_key for r in rows}), "total_papers": total_papers,
        "years": years,
    }


def _target_weights(
    target: str, rows: Sequence[Observation], systems: Sequence[str], alpha: float
) -> list[Weight]:
    total = sum(r.count for r in rows)
    papers = len({r.paper_key for r in rows})
    by_system: dict[str, list[Observation]] = defaultdict(list)
    by_topic: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for row in rows:
        by_system[row.curriculum_code].append(row)
        if row.topic:
            by_topic[(row.curriculum_code, row.topic)].append(row)
    out: list[Weight] = []
    k = len(systems)
    for code in systems:
        hits = by_system.get(code, [])
        value = (sum(r.count for r in hits) + alpha) / (total + alpha * k)
        out.append(Weight(target, code, "", round(value, 6),
                          _basis(hits, total, papers, k, alpha)))
    t = len(by_topic)
    for (code, topic), hits in sorted(by_topic.items()):
        value = (sum(r.count for r in hits) + alpha) / (total + alpha * t)
        out.append(Weight(target, code, topic, round(value, 6),
                          _basis(hits, total, papers, t, alpha)))
    return out


def compute_weights(
    observations: Iterable[Observation], systems: Sequence[str], alpha: float = ALPHA
) -> list[Weight]:
    """Weights per exam target plus the ``all`` aggregate; empty input -> []."""
    if alpha <= 0:
        raise ValueError("alpha must be positive")
    known = set(systems)
    rows = [o for o in observations if o.curriculum_code in known and o.count > 0]
    if not rows:
        return []
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for row in rows:
        grouped[row.exam_target].append(row)
    grouped[ALL] = rows
    weights: list[Weight] = []
    for target in sorted(grouped):
        weights.extend(_target_weights(target, grouped[target], systems, alpha))
    return weights
