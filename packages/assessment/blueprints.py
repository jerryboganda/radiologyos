"""Exam blueprints: packaged per-exam defaults, owner overrides, and sizing (ADR 0023).

A blueprint describes one mock sitting: item counts per type, duration, the
per-system mix, negative marking, and a pass mark when one is public. Facts
that could not be confirmed from a public source are listed in ``unverified``
and shown as such. A tenant may override the editable fields; the effective
blueprint is the default merged with the override and revalidated, and an
approval is bound to the effective blueprint's hash.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.curriculum.contracts import ExamTag
from packages.curriculum.loader import radiology_pack

ItemType = Literal["sba", "seq", "image_case", "viva"]
PATH = Path(__file__).resolve().parent / "blueprints.json"
EDITABLE = frozenset({"items", "duration_minutes", "mix_mode", "mix", "negative_marking",
                      "pass_mark_percent"})
SHARE_TOLERANCE = 1e-3


class MixGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=120)
    systems: tuple[str, ...] = Field(min_length=1)
    share: float = Field(gt=0, le=1)


class NegativeMarking(BaseModel):
    """``penalty`` is the fraction of an item's mark lost for a wrong SBA answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    penalty: float = Field(default=0.0, ge=0, le=1)


class Blueprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]{1,60}$")
    title: str = Field(min_length=1, max_length=200)
    exam_target: Literal["fcps2_theory", "fcps2_toacs", "imm", "frcr"]
    curriculum_tag: ExamTag
    items: dict[ItemType, int]
    duration_minutes: int = Field(ge=1, le=600)
    mix_mode: Literal["fixed", "even", "weights"]
    mix: tuple[MixGroup, ...] = ()
    negative_marking: NegativeMarking = NegativeMarking()
    pass_mark_percent: float | None = Field(default=None, ge=0, le=100)
    unverified: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    notes: str = ""

    @model_validator(mode="after")
    def check(self) -> Blueprint:
        if any(n < 0 or n > 300 for n in self.items.values()) or self.total_items() < 1:
            raise ValueError("item counts must be 0..300 with at least one item")
        if self.mix_mode == "fixed":
            if not self.mix:
                raise ValueError("a fixed mix needs at least one group")
            if abs(sum(g.share for g in self.mix) - 1) > SHARE_TOLERANCE:
                raise ValueError("mix shares must sum to 1")
        known = {n.code for n in radiology_pack().nodes if n.level == "system"}
        unknown = {s for g in self.mix for s in g.systems} - known
        if unknown:
            raise ValueError(f"unknown mix systems: {sorted(unknown)}")
        if self.negative_marking.enabled and self.negative_marking.penalty <= 0:
            raise ValueError("negative marking needs a positive penalty")
        return self

    def total_items(self) -> int:
        return sum(self.items.values())

    def penalty(self) -> float:
        return self.negative_marking.penalty if self.negative_marking.enabled else 0.0


@lru_cache(maxsize=1)
def packaged() -> dict[str, Blueprint]:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    blueprints = [Blueprint.model_validate(item) for item in data["blueprints"]]
    return {bp.id: bp for bp in blueprints}


def effective(default: Blueprint, overrides: Mapping[str, Any] | None) -> Blueprint:
    """The default with the override applied and revalidated; bad keys raise ValueError."""
    extra = set(overrides or {}) - EDITABLE
    if extra:
        raise ValueError(f"these blueprint fields cannot be overridden: {sorted(extra)}")
    merged = {**default.model_dump(mode="json"), **(overrides or {})}
    return Blueprint.model_validate(merged)


def blueprint_hash(blueprint: Blueprint) -> str:
    payload = json.dumps(blueprint.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def largest_remainder(total: int, shares: Sequence[float]) -> list[int]:
    """Split ``total`` into integers proportional to ``shares`` (ties to the first)."""
    weight = sum(shares)
    if total <= 0 or weight <= 0:
        return [0] * len(shares)
    exact = [total * s / weight for s in shares]
    counts = [math.floor(x) for x in exact]
    order = sorted(range(len(shares)), key=lambda i: (-(exact[i] - counts[i]), i))
    for i in order[: total - sum(counts)]:
        counts[i] += 1
    return counts


def scaled_items(blueprint: Blueprint, total: int | None) -> dict[str, int]:
    """Item counts per type, scaled to ``total`` items (None keeps the full paper)."""
    types = [t for t, n in blueprint.items.items() if n > 0]
    if total is None or total >= blueprint.total_items():
        return {t: blueprint.items[t] for t in types}
    counts = largest_remainder(total, [blueprint.items[t] for t in types])
    return {t: n for t, n in zip(types, counts, strict=True) if n > 0}


def minutes_for(blueprint: Blueprint, items: int) -> int:
    """Duration pro rata to the number of items, rounded up, at least one minute."""
    return max(1, math.ceil(blueprint.duration_minutes * items / blueprint.total_items()))


def mix_groups(blueprint: Blueprint, weights: Mapping[str, float] | None = None) -> list[MixGroup]:
    """The groups a paper is drawn from.

    ``fixed`` uses the blueprint's groups; ``even`` gives every system tagged
    for the blueprint's exam an equal share; ``weights`` uses the owner's
    approved system weights over those systems, falling back to even.
    """
    if blueprint.mix_mode == "fixed":
        return list(blueprint.mix)
    systems = [n for n in radiology_pack().nodes
               if n.level == "system" and blueprint.curriculum_tag in n.exams]
    shares = [1.0] * len(systems)
    if blueprint.mix_mode == "weights" and weights:
        picked = [max(0.0, float(weights.get(n.code, 0.0))) for n in systems]
        if sum(picked) > 0:
            shares = picked
    total = sum(shares)
    return [MixGroup(label=n.title, systems=(n.code,), share=s / total)
            for n, s in zip(systems, shares, strict=True) if s > 0]
