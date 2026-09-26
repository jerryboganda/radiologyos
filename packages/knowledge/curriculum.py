"""Curriculum codes offered to the classifiers (the draft radiology pack, ADR 0023).

System codes are stable and remain what ``curriculum_mappings.curriculum_code``,
cards, and system-level weights store. Topic codes (``CHEST.PULM_VASC``) and
subtopic codes (``CHEST.PULM_VASC.PE``) sit below them; a mapping keeps its
system in ``curriculum_code`` and the most specific node in ``curriculum_node_id``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple

from packages.curriculum.candidates import validate_node_id
from packages.curriculum.contracts import CurriculumPack
from packages.curriculum.loader import radiology_pack, system_of

REVIEW_BELOW = 0.7


def pack() -> CurriculumPack:
    return radiology_pack()


@lru_cache(maxsize=1)
def system_codes() -> tuple[str, ...]:
    return tuple(node.code for node in pack().nodes if node.level == "system")


def prompt_listing() -> str:
    """One 'CODE: Title' line per system, for the system-level classifier prompts."""
    return "\n".join(f"{n.code}: {n.title}" for n in pack().nodes if n.level == "system")


def mapping_status(code: str, confidence: float) -> str | None:
    """'accepted', 'review' (< 0.7, editor queue), or None for unknown codes."""
    if code not in system_codes():
        return None
    return "accepted" if confidence >= REVIEW_BELOW else "review"


class NodeMapping(NamedTuple):
    system: str
    node_id: str
    status: str


def node_mapping(node_id: str, confidence: float) -> NodeMapping | None:
    """Resolve a node id at any depth to (system, node, status); None if unknown.

    The review rule is the system-level one: confidence < 0.7 goes to review.
    """
    node = validate_node_id(node_id)
    system = system_of(node) if node is not None else None
    if node is None or system is None:
        return None
    return NodeMapping(system, node, "accepted" if confidence >= REVIEW_BELOW else "review")
