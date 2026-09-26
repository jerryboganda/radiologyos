"""Curriculum codes offered to the classifiers (the unvalidated seed pack)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from packages.curriculum.contracts import CurriculumPack, load_curriculum_pack

PACK = Path(__file__).resolve().parents[1] / "curriculum" / "fcps2_radiology.json"
REVIEW_BELOW = 0.7


@lru_cache(maxsize=1)
def pack() -> CurriculumPack:
    return load_curriculum_pack(PACK)


def system_codes() -> tuple[str, ...]:
    return tuple(node.code for node in pack().nodes if node.level == "system")


def prompt_listing() -> str:
    """One 'CODE: Title' line per system, for the classifier prompts."""
    return "\n".join(f"{n.code}: {n.title}" for n in pack().nodes if n.level == "system")


def mapping_status(code: str, confidence: float) -> str | None:
    """'accepted', 'review' (< 0.7, editor queue), or None for unknown codes."""
    if code not in system_codes():
        return None
    return "accepted" if confidence >= REVIEW_BELOW else "review"
