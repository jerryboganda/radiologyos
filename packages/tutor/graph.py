"""Knowledge-graph expansion of tutor context (ADR 0028), pure selection logic.

Seeds are the concepts whose claims were extracted from the top retrieved
chunks; their 1-hop ``concept_edges`` neighbours are added, preferring the
relations that suit the question's intent (differentials for a DDx,
contrasts for a comparison). Claims of seeds and neighbours become extra
citable excerpts labelled ``K1``..: the excerpt text is the claim's verbatim
**evidence span** from its source chunk (so the grounding judge checks answers
against the source, not against the extracted paraphrase), and the citation is
that chunk's source, pages and blocks. A claim without a chunk, an evidence
span, or pages is never offered. The whole expansion is bounded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from packages.tutor.grounding import Excerpt
from packages.tutor.intent import Intent


@dataclass(frozen=True, slots=True)
class GraphBudget:
    seed_chunks: int = 4
    seed_concepts: int = 4
    neighbours: int = 6
    claims: int = 6
    per_concept: int = 2
    span_chars: int = 600


DEFAULT_BUDGET = GraphBudget()
BUDGETS: Mapping[Intent, GraphBudget] = {
    "ddx": GraphBudget(neighbours=8, claims=8),
    "compare": GraphBudget(neighbours=8, claims=8),
    "quiz": GraphBudget(seed_chunks=0, seed_concepts=0, neighbours=0, claims=0),
}
PREFERRED: Mapping[Intent, tuple[str, ...]] = {
    "ddx": ("differential_of", "contrasts_with", "sign_of"),
    "compare": ("contrasts_with", "differential_of", "is_a"),
    "show_me": ("seen_on", "sign_of"),
    "report": ("classified_by", "sign_of"),
}


@dataclass(frozen=True, slots=True)
class Neighbour:
    concept_id: UUID
    relation: str
    seed_id: UUID


def budget_for(intent: Intent) -> GraphBudget:
    return BUDGETS.get(intent, DEFAULT_BUDGET)


def pick_neighbours(
    edges: Sequence[Mapping[str, Any]], seeds: Sequence[UUID], intent: Intent, limit: int
) -> list[Neighbour]:
    """1-hop neighbours of the seeds (not seeds themselves), preferred relations first."""
    seed_rank = {seed: i for i, seed in enumerate(seeds)}
    preferred = PREFERRED.get(intent, ())
    found: dict[UUID, tuple[tuple[int, int], Neighbour]] = {}
    for edge in edges:
        a, b, relation = edge["from_concept"], edge["to_concept"], str(edge["relation"])
        for seed, other in ((a, b), (b, a)):
            if seed not in seed_rank or other in seed_rank:
                continue
            key = (preferred.index(relation) if relation in preferred else len(preferred),
                   seed_rank[seed])
            if other not in found or key < found[other][0]:
                found[other] = (key, Neighbour(other, relation, seed))
    ranked = sorted(found.values(), key=lambda item: item[0])
    return [neighbour for _, neighbour in ranked[:limit]]


def _block_refs(citation: Any) -> list[dict[str, int]]:
    if isinstance(citation, str):
        try:
            citation = json.loads(citation)
        except ValueError:
            return []
    blocks = citation.get("blocks") if isinstance(citation, Mapping) else None
    refs: list[dict[str, int]] = []
    for block in blocks or []:
        page, number = block.get("page_no"), block.get("block_no")
        if isinstance(page, int) and isinstance(number, int):
            refs.append({"page_no": page, "block_no": number})
    return refs


def citable(row: Mapping[str, Any]) -> bool:
    """A claim is offered only with its evidence reference: chunk, span, pages."""
    return (row.get("chunk_id") is not None and row.get("source_id") is not None
            and bool(str(row.get("evidence_span") or "").strip())
            and isinstance(row.get("page_from"), int) and isinstance(row.get("page_to"), int))


def _heading(row: Mapping[str, Any], via: Neighbour | None, names: Mapping[UUID, str]) -> str:
    name = str(row["concept_name"])
    if via is None:
        return f"Knowledge graph: {name}"
    relation = via.relation.replace("_", " ")
    return f"Knowledge graph: {name} ({relation} {names.get(via.seed_id, 'a matched concept')})"


def select_claims(
    rows: Sequence[Mapping[str, Any]], seeds: Sequence[UUID], neighbours: Sequence[Neighbour],
    budget: GraphBudget, exclude_chunks: set[UUID], names: Mapping[UUID, str],
) -> list[Excerpt]:
    """Bounded, labelled K1..Kn claim excerpts: seeds first, then neighbours."""
    via = {n.concept_id: n for n in neighbours}
    order = {cid: i for i, cid in enumerate([*seeds, *(n.concept_id for n in neighbours)])}
    usable = [r for r in rows if r["concept_id"] in order and citable(r)
              and r["chunk_id"] not in exclude_chunks]
    usable.sort(key=lambda r: (order[r["concept_id"]], r.get("verification") != "verified",
                               -int(r.get("importance") or 0)))
    per_concept: dict[UUID, int] = {}
    seen_spans: set[str] = set()
    out: list[Excerpt] = []
    for row in usable:
        span = " ".join(str(row["evidence_span"]).split())[: budget.span_chars]
        if len(out) >= budget.claims or span.lower() in seen_spans:
            continue
        if per_concept.get(row["concept_id"], 0) >= budget.per_concept:
            continue
        per_concept[row["concept_id"]] = per_concept.get(row["concept_id"], 0) + 1
        seen_spans.add(span.lower())
        out.append(Excerpt(
            label=f"K{len(out) + 1}", chunk_id=row["chunk_id"], source_id=row["source_id"],
            source_title=str(row["source_title"]), page_from=row["page_from"],
            page_to=row["page_to"], heading=_heading(row, via.get(row["concept_id"]), names),
            text=span, block_refs=_block_refs(row.get("citation")),
        ))
    return out
