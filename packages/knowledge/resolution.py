"""Entity-resolution decision (spec section 5), independent of the database.

| similarity to an existing concept     | action                                   |
| alias/normalised-name match or >= 0.92 | merge into it and record the new alias   |
| 0.80 - 0.92                            | new concept, flagged ``near`` for review |
| < 0.80                                 | new concept                              |

The spec routes the 0.80-0.92 band to a ``reason`` adjudicator; until that
agent exists the concepts stay separate (safe: no silent merge) and the near
match is returned so callers can surface it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from packages.knowledge.text import AUTO_MERGE, CANDIDATE, trigram_similarity


@dataclass(frozen=True, slots=True)
class Candidate:
    id: UUID
    normalized_name: str
    alias_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Decision:
    action: str  # "merge" | "new"
    concept_id: UUID | None
    similarity: float
    near: UUID | None = None


def decide(keys: Sequence[str], candidates: Sequence[Candidate]) -> Decision:
    """Pick merge/new for a concept whose normalised keys are ``keys``."""
    wanted = set(keys)
    for candidate in candidates:
        if candidate.normalized_name in wanted or wanted & set(candidate.alias_keys):
            return Decision("merge", candidate.id, 1.0)
    best: tuple[float, UUID | None] = (0.0, None)
    for candidate in candidates:
        score = max(
            trigram_similarity(key, other)
            for key in keys
            for other in (candidate.normalized_name, *candidate.alias_keys)
        )
        if score > best[0]:
            best = (score, candidate.id)
    if best[0] >= AUTO_MERGE:
        return Decision("merge", best[1], best[0])
    near = best[1] if best[0] >= CANDIDATE else None
    return Decision("new", None, best[0], near)


def merged_aliases(
    existing_aliases: Sequence[str], existing_keys: Sequence[str],
    new_aliases: Sequence[str], new_keys: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Order-preserving union of display aliases and match keys for a merge."""
    out_aliases = list(existing_aliases)
    out_aliases.extend(a for a in dict.fromkeys(new_aliases) if a not in out_aliases)
    out_keys = list(existing_keys)
    out_keys.extend(k for k in dict.fromkeys(new_keys) if k not in out_keys)
    return out_aliases[:40], out_keys[:40]
