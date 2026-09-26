"""Coverage heatmap by system and topic (spec section 7), for a curriculum of any depth.

The curriculum is a tree (section -> system -> topic -> subtopic ...). Each
system is a row; its direct children are the cells, and anything mapped deeper
rolls up into the child it sits under. Material mapped to the system itself
lands in a "General" cell, and a system with no children has one cell for the
whole system. A cell's value is its coverage (share of its mapped passages
studied); accuracy is shown beside it when there are attempts. The system row
carries the planner's mastery band. No pass probability is derived.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from packages.study.mastery import band_for


@dataclass(frozen=True, slots=True)
class Node:
    code: str
    parent_code: str | None
    level: str
    title: str


@dataclass(slots=True)
class CodeStats:
    """Per curriculum code: mapped passages, passages studied, graded attempt totals."""

    material: int = 0
    studied: int = 0
    score: float = 0.0
    max_score: float = 0.0

    def add(self, other: CodeStats) -> None:
        self.material += other.material
        self.studied += other.studied
        self.score += other.score
        self.max_score += other.max_score


@dataclass(frozen=True, slots=True)
class SystemMastery:
    code: str
    mastery: float
    band: str
    coverage: float
    weight: float


def parents(nodes: Iterable[Node]) -> dict[str, str | None]:
    return {node.code: node.parent_code for node in nodes}


def ancestors(code: str, parent_of: Mapping[str, str | None]) -> list[str]:
    """``code`` and every ancestor, nearest first (cycle-safe)."""
    chain: list[str] = []
    current: str | None = code
    while current is not None and current not in chain:
        chain.append(current)
        current = parent_of.get(current)
    return chain


def within(code: str | None, root: str, parent_of: Mapping[str, str | None]) -> bool:
    """True when ``code`` is ``root`` or sits anywhere beneath it."""
    return code is not None and root in ancestors(code, parent_of)


def subtree(root: str, nodes: Sequence[Node]) -> list[str]:
    parent_of = parents(nodes)
    return [n.code for n in nodes if within(n.code, root, parent_of)] or [root]


def _cell(code: str, title: str, stats: CodeStats) -> dict[str, Any]:
    coverage = stats.studied / stats.material if stats.material else None
    accuracy = stats.score / stats.max_score if stats.max_score else None
    return {
        "code": code, "title": title, "material": stats.material, "studied": stats.studied,
        "coverage": None if coverage is None else round(min(coverage, 1.0), 4),
        "accuracy": None if accuracy is None else round(accuracy, 4),
        "band": "none" if coverage is None else band_for(coverage),
    }


def _row(system: Node, children: list[Node], stats: Mapping[str, CodeStats],
         parent_of: Mapping[str, str | None]) -> list[dict[str, Any]]:
    if not children:
        total = CodeStats()
        for code, value in stats.items():
            if within(code, system.code, parent_of):
                total.add(value)
        return [_cell(system.code, "All topics", total)]
    buckets = {child.code: CodeStats() for child in children}
    general = CodeStats()
    for code, value in stats.items():
        chain = ancestors(code, parent_of)
        if system.code not in chain:
            continue
        child = next((c for c in chain if c in buckets), None)
        (buckets[child] if child else general).add(value)
    cells = [_cell(c.code, c.title, buckets[c.code]) for c in children]
    if general.material:
        cells.append(_cell(system.code, "General", general))
    return cells


def build(nodes: Sequence[Node], stats: Mapping[str, CodeStats],
          systems: Sequence[SystemMastery]) -> list[dict[str, Any]]:
    """One row per curriculum system, in curriculum order."""
    parent_of = parents(nodes)
    by_code = {s.code: s for s in systems}
    rows = []
    for system in (n for n in nodes if n.level == "system"):
        children = [n for n in nodes if n.parent_code == system.code]
        known = by_code.get(system.code)
        rows.append({
            "code": system.code, "title": system.title,
            "mastery": known.mastery if known else 0.0,
            "band": known.band if known else "weak",
            "coverage": known.coverage if known else 0.0,
            "weight": known.weight if known else 0.0,
            "cells": _row(system, children, stats, parent_of),
        })
    return rows
