"""Claim-based SBA generation inputs and checks (``question_generate/v2``, ADR 0029).

The generator sees a topic's verified claims as numbered excerpts (``C1``..),
each with its verbatim evidence span and the claim's own provenance (source,
pages, evidence blocks), plus the concept graph's neighbours of the topic:
differentials and contrasts first, then siblings under a shared parent. A
neighbour that has a usable claim of its own is also supplied as an excerpt, so
a distractor's rationale can cite why that entity is wrong. Code then checks
that enough distractors name a supplied neighbour (by name or alias, compared
after normalisation), so distractors really come from the graph.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from packages.assessment.models import GeneratedItem
from packages.assessment.validation import Excerpt
from packages.knowledge.text import normalize_name
from packages.study.knowledge_cards import claim_citation

MIN_CLAIMS = 3
MAX_CLAIMS = 10
MAX_NEIGHBOURS = 12
MAX_NEIGHBOUR_CLAIMS = 6
MIN_GRAPH_DISTRACTORS = 2
MIN_NAME_CHARS = 3
EXCERPT_CHARS = 1500


@dataclass(frozen=True, slots=True)
class Neighbour:
    name: str
    aliases: tuple[str, ...]
    relation: str

    def keys(self) -> set[str]:
        return {k for k in (normalize_name(n) for n in (self.name, *self.aliases))
                if len(k) >= MIN_NAME_CHARS}


def claim_excerpt(ref: str, claim: Mapping[str, Any], note: str = "") -> Excerpt | None:
    """One claim as a numbered excerpt citing its evidence; None without provenance."""
    citation = claim_citation(claim)
    if citation is None:
        return None
    body = (f"Claim about {claim.get('concept_name', '')}: {claim['statement']}\n"
            f"Evidence: {' '.join(str(claim['evidence_span']).split())}")
    heading = f"{note} {claim.get('concept_name', '')}".strip()
    return Excerpt(ref=ref, heading=heading, text=body[:EXCERPT_CHARS], citation=citation)


def neighbours_of(rows: Iterable[Mapping[str, Any]]) -> list[Neighbour]:
    return [Neighbour(name=str(r["name"]), aliases=tuple(str(a) for a in r.get("aliases") or []),
                      relation=str(r["relation"])) for r in rows][:MAX_NEIGHBOURS]


def build_material(
    claims: Sequence[Mapping[str, Any]], neighbour_rows: Sequence[Mapping[str, Any]],
    neighbour_claims: Sequence[Mapping[str, Any]],
) -> tuple[list[Excerpt], list[Neighbour]] | None:
    """Excerpts (topic claims, then one claim per neighbour) and neighbours; None if too few."""
    excerpts: list[Excerpt] = []
    for claim in claims[:MAX_CLAIMS]:
        excerpt = claim_excerpt(f"C{len(excerpts) + 1}", claim)
        if excerpt is not None:
            excerpts.append(excerpt)
    neighbours = neighbours_of(neighbour_rows)
    if len(excerpts) < MIN_CLAIMS or len(neighbours) < MIN_GRAPH_DISTRACTORS:
        return None
    seen: set[str] = set()
    for claim in neighbour_claims:
        concept = str(claim["concept_id"])
        if concept in seen or len(seen) >= MAX_NEIGHBOUR_CLAIMS:
            continue
        excerpt = claim_excerpt(f"C{len(excerpts) + 1}", claim, note="Neighbour:")
        if excerpt is not None:
            seen.add(concept)
            excerpts.append(excerpt)
    return excerpts, neighbours


def render_neighbours(neighbours: Sequence[Neighbour]) -> str:
    if not neighbours:
        return "(none)"
    lines = []
    for n in neighbours:
        aka = f" (also: {', '.join(n.aliases[:3])})" if n.aliases else ""
        lines.append(f"- {n.name}{aka} [{n.relation}]")
    return "\n".join(lines)


def _names_neighbour(option_text: str, keys: Sequence[set[str]]) -> bool:
    option = normalize_name(option_text)
    return any(k == option or f" {k} " in f" {option} " for group in keys for k in group)


def graph_distractors(item: GeneratedItem, neighbours: Sequence[Neighbour]) -> int:
    """How many non-key options name a supplied graph neighbour."""
    keys = [n.keys() for n in neighbours]
    return sum(1 for i, option in enumerate(item.options)
               if i != item.key_index and _names_neighbour(option.text, keys))


def claim_problems(item: GeneratedItem, neighbours: Sequence[Neighbour]) -> list[str]:
    """Claim-path checks on top of ``validation.check_item``."""
    if item.type != "sba":
        return ["claim_basis_is_sba_only"]
    if graph_distractors(item, neighbours) < MIN_GRAPH_DISTRACTORS:
        return ["too_few_graph_distractors"]
    return []
