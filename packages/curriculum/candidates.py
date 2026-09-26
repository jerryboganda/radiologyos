"""Curriculum node ids a classifier prompt may emit, and their validation (ADR 0023).

A node id is the code of any system, topic, or subtopic in the radiology pack
(``CHEST``, ``CHEST.PULM_VASC``, ``CHEST.PULM_VASC.PE``). Prompts embed the
listing from ``candidate_listing`` and must emit, per chunk or question,
``{"curriculum_node_id": str, "confidence": float}``; ``validate_node_id``
returns the canonical id or None, so an invented id is dropped, never stored.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict

from packages.curriculum.contracts import EXAM_TAGS, CurriculumNode
from packages.curriculum.loader import node_index, radiology_pack

# Knowledge/assessment exam targets map onto pack tags; FRCR covers 2A and 2B.
TARGET_TAGS: dict[str, tuple[str, ...]] = {
    "imm": ("imm",), "fcps2_theory": ("fcps2_theory",), "fcps2_toacs": ("fcps2_toacs",),
    "frcr": ("frcr_2a", "frcr_2b"), "frcr_2a": ("frcr_2a",), "frcr_2b": ("frcr_2b",),
}
_LEVELS = ("system", "topic", "subtopic")


class Candidate(TypedDict):
    id: str
    path: str
    label: str
    level: str


def tags_for(exam_targets: Iterable[str] | None) -> frozenset[str]:
    """Pack tags for the given targets; None or empty (or 'unknown'/'all') means every tag."""
    tags: set[str] = set()
    for target in exam_targets or ():
        tags.update(TARGET_TAGS.get(target, ()))
    return frozenset(tags or EXAM_TAGS)


def _path(node: CurriculumNode, index: dict[str, CurriculumNode]) -> str:
    titles: list[str] = []
    current: CurriculumNode | None = node
    while current is not None and current.level != "section":
        titles.append(current.title)
        current = index.get(current.parent_code or "")
    return " > ".join(reversed(titles))


def topic_candidates(
    exam_targets: Iterable[str] | None = None, max_level: str = "subtopic"
) -> list[Candidate]:
    """Valid node ids (pack order) applicable to any of the targets, down to ``max_level``."""
    if max_level not in _LEVELS:
        raise ValueError(f"max_level must be one of {_LEVELS}")
    allowed = _LEVELS[: _LEVELS.index(max_level) + 1]
    wanted = tags_for(exam_targets)
    index = node_index()
    return [
        Candidate(id=n.code, path=_path(n, index), label=n.title, level=n.level)
        for n in radiology_pack().nodes
        if n.level in allowed and wanted & set(n.exams)
    ]


def candidate_listing(
    exam_targets: Iterable[str] | None = None, max_level: str = "subtopic"
) -> str:
    """One 'ID | System > Topic > Subtopic' line per candidate, for prompts."""
    return "\n".join(f"{c['id']} | {c['path']}"
                     for c in topic_candidates(exam_targets, max_level))


def validate_node_id(node_id: str) -> str | None:
    """The canonical node id (system, topic, or subtopic) or None if unknown."""
    code = node_id.strip().upper()
    node = node_index().get(code)
    return code if node is not None and node.level in _LEVELS else None
