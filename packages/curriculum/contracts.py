"""Typed contracts for curriculum packs (ADR 0016, ADR 0023).

A pack is a flat list of nodes forming one tree: a single ``section`` root,
``system`` children, then ``topic`` and ``subtopic`` levels. Schema version 2
adds per-exam applicability tags and hierarchical codes: a topic code is its
system code plus ``.SUFFIX`` and a subtopic code its topic code plus ``.SUFFIX``,
so system codes (used by existing mappings and weights) never change. Draft
and placeholder packs carry no exam weights: weights come from past papers and
the owner's approval, never from the pack.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExamTag = Literal["fcps2_theory", "fcps2_toacs", "imm", "frcr_2a", "frcr_2b"]
EXAM_TAGS: tuple[ExamTag, ...] = ("fcps2_theory", "fcps2_toacs", "imm", "frcr_2a", "frcr_2b")
Level = Literal["section", "system", "topic", "subtopic"]
PackStatus = Literal["placeholder_unvalidated", "draft_pending_owner_approval", "editor_validated"]
_PARENT_LEVEL: dict[str, str] = {"system": "section", "topic": "system", "subtopic": "topic"}
_UNWEIGHTED = ("placeholder_unvalidated", "draft_pending_owner_approval")


class CurriculumNode(BaseModel):
    """One editable ontology node; weights remain unassigned by default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9:._-]*$", max_length=120)
    parent_code: str | None = None
    level: Level
    title: str = Field(min_length=1, max_length=200)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    exams: tuple[ExamTag, ...] = ()


class CurriculumPack(BaseModel):
    """A curriculum release; only the owner's in-app approval validates a draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 1
    pack_id: str = Field(default="fcps2_radiology", pattern=r"^[a-z0-9_]+$")
    version: str = Field(default="0", min_length=1, max_length=40)
    status: PackStatus
    source: str = Field(min_length=1)
    sources: tuple[str, ...] = ()
    exam_blueprint: str | None = None
    nodes: tuple[CurriculumNode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ontology(self) -> CurriculumPack:
        codes = [node.code for node in self.nodes]
        if len(codes) != len(set(codes)):
            raise ValueError("curriculum node codes must be unique")
        by_code = {node.code: node for node in self.nodes}
        for node in self.nodes:
            if node.parent_code is not None and node.parent_code not in by_code:
                raise ValueError(f"unknown curriculum parent: {node.parent_code}")
        if sum(node.level == "section" for node in self.nodes) != 1:
            raise ValueError("curriculum requires exactly one root section")
        if self.status in _UNWEIGHTED and any(n.exam_weight is not None for n in self.nodes):
            raise ValueError("an unapproved curriculum must not assign exam weights")
        if self.status in _UNWEIGHTED and self.exam_blueprint is not None:
            raise ValueError("an unapproved curriculum must not assign a blueprint")
        if self.schema_version == 2:
            for node in self.nodes:
                _check_v2_node(node, by_code)
        return self


def _check_v2_node(node: CurriculumNode, by_code: dict[str, CurriculumNode]) -> None:
    """Hierarchy, code-prefix, and exam-tag rules for schema version 2."""
    if node.level == "section":
        if node.parent_code is not None:
            raise ValueError("the root section has no parent")
        return
    parent = by_code.get(node.parent_code or "")
    if parent is None or parent.level != _PARENT_LEVEL[node.level]:
        expected = _PARENT_LEVEL[node.level]
        raise ValueError(f"{node.code}: a {node.level} must sit under a {expected}")
    if node.level != "system" and not node.code.startswith(parent.code + "."):
        raise ValueError(f"{node.code}: code must extend its parent code {parent.code}")
    if not node.exams:
        raise ValueError(f"{node.code}: at least one exam tag is required")
    if parent.level != "section" and not set(node.exams) <= set(parent.exams):
        raise ValueError(f"{node.code}: exam tags must be a subset of the parent's")


def pack_hash(pack: CurriculumPack) -> str:
    """Stable SHA-256 of the pack content; an approval is bound to this hash."""
    payload = json.dumps(pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_curriculum_pack(path: Path) -> CurriculumPack:
    """Load and validate a flat curriculum JSON pack."""

    return CurriculumPack.model_validate_json(path.read_text(encoding="utf-8"))
