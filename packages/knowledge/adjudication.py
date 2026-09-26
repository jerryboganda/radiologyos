"""Policies for the Resolver and Conflict agents, and reversible merge planning.

Pure functions (no database, no model) so the rules are unit-tested directly
(ADR 0030):

* Resolver: a confident ``merge`` (>= 0.85) is applied; a confident
  ``distinct``/``parent_child`` is recorded and the pair is not asked again;
  anything less confident goes to the owner's review queue.
* Conflict agent: ``conflict`` keeps the conflict open (with the rationale); a
  confident ``context``/``same`` (>= 0.80) closes it with both claims kept;
  anything less confident stays open for the owner.
* A merge keeps the smaller concept as a redirect (``merged_into``) and records
  exactly what it added to the survivor, so undoing it removes only that.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MERGE_CONFIDENCE = 0.85
CONFLICT_CONFIDENCE = 0.80
MAX_ALIASES = 40


def resolver_action(decision: str, confidence: float) -> str:
    """``merge`` | ``distinct`` | ``review`` for a model decision."""
    if confidence < MERGE_CONFIDENCE:
        return "review"
    return "merge" if decision == "merge" else "distinct"


def conflict_action(label: str, confidence: float) -> str:
    """``keep_open`` | ``auto_resolve`` for a model verdict on a heuristic conflict."""
    if label in ("context", "same") and confidence >= CONFLICT_CONFIDENCE:
        return "auto_resolve"
    return "keep_open"


def conflict_resolution_text(label: str, rationale: str, context: str) -> str:
    head = "Same fact in both sources" if label == "same" else "Both valid in context"
    detail = f" ({context.strip()})" if context.strip() else ""
    return f"{head}{detail}. Model rationale: {rationale.strip()}"[:2000]


def choose_survivor(
    a: Mapping[str, Any], b: Mapping[str, Any]
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """(survivor, merged): more claims wins, then the older concept, then the id."""
    def rank(c: Mapping[str, Any]) -> tuple[int, str, str]:
        return (-int(c.get("claim_count") or 0), str(c.get("created_at") or ""), str(c["id"]))

    first, second = sorted((a, b), key=rank)
    return first, second


def merge_additions(
    survivor: Mapping[str, Any], merged: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """(aliases, keys) the merge adds to the survivor; only these are undone later."""
    have_aliases = set(survivor.get("aliases") or ()) | {survivor["name"]}
    have_keys = set(survivor.get("alias_keys") or ()) | {survivor["normalized_name"]}
    room_aliases = max(0, MAX_ALIASES - len(survivor.get("aliases") or ()))
    room_keys = max(0, MAX_ALIASES - len(survivor.get("alias_keys") or ()))
    aliases = [a for a in dict.fromkeys([merged["name"], *(merged.get("aliases") or ())])
               if a and a not in have_aliases][:room_aliases]
    keys = [k for k in dict.fromkeys([merged["normalized_name"], *(merged.get("alias_keys") or ())])
            if k and k not in have_keys][:room_keys]
    return aliases, keys


def without(values: Sequence[str], removed: Sequence[str]) -> list[str]:
    """``values`` minus exactly the entries a merge added (order kept)."""
    drop = set(removed)
    return [v for v in values if v not in drop]


def pair_key(a: str, b: str) -> tuple[str, str]:
    """Canonical order for a concept pair (one decision per unordered pair)."""
    return (a, b) if a < b else (b, a)
