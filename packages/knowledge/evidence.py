"""Evidence-span enforcement and block-level provenance for extracted claims.

Spec section 5: a claim is rejected if its ``evidence_span`` is not a verbatim
substring of the chunk. Only whitespace differences are tolerated (PDF text
layers wrap lines arbitrarily); the stored span is then the whitespace-collapsed
form, which is still a verbatim substring of the whitespace-collapsed chunk.
Rejected claims are counted, never stored and never logged with their text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from packages.knowledge.models import (
    ExtractedClaim,
    ExtractedConcept,
    ExtractedRelation,
    KnowledgeExtraction,
)
from packages.knowledge.support import supported_span
from packages.knowledge.text import collapse_ws, normalize_name

MIN_SPAN_CHARS = 8
_SEGMENT = re.compile(r"(?<=[?.!])\s+|\s*(?=\bQ\d+[.):])")
_ASKS = re.compile(r"^(q\d+[.):]?\s*)?(what|which|how|why|where|when|who|name|describe|list|"
                   r"identify|enumerate|give)\b", re.IGNORECASE)
_LABEL = re.compile(r"^(q\d+|ans|answer|answar)[.):]?$", re.IGNORECASE)
_BULLETS = " \t\r\n-•�"


def only_questions(span: str) -> bool:
    """True when every sentence of the span asks rather than states (e.g. "Q2. What is...")."""
    parts = [p.strip(_BULLETS) for p in _SEGMENT.split(span)]
    parts = [p for p in parts if p and not _LABEL.match(p)]
    return bool(parts) and all(p.endswith("?") or _ASKS.match(p) for p in parts)


def verify_span(span: str, chunk_text: str) -> str | None:
    """Return the span to store if it is verbatim in the chunk, else None.

    A span that only quotes exam questions states nothing, so it never supports a claim.
    """
    if len(span.strip()) < MIN_SPAN_CHARS or only_questions(span):
        return None
    if span in chunk_text:
        return span
    collapsed = collapse_ws(span)
    if collapsed and collapsed in collapse_ws(chunk_text):
        return collapsed
    return None


@dataclass(slots=True)
class FilteredExtraction:
    concepts: list[ExtractedConcept]
    claims: list[ExtractedClaim]
    relations: list[ExtractedRelation]
    rejected_claims: int = 0
    rejected_relations: int = 0


def filter_extraction(result: KnowledgeExtraction, chunk_text: str) -> FilteredExtraction:
    """Drop unsupported claims, add concepts claims refer to, dedupe by key."""
    concepts: dict[str, ExtractedConcept] = {}
    for concept in result.concepts:
        key = normalize_name(concept.name)
        if key and key not in concepts:
            concepts[key] = concept
    claims: list[ExtractedClaim] = []
    rejected = 0
    for claim in result.claims:
        span = verify_span(claim.evidence_span, chunk_text)
        # Over-reach (ADR 0037): the evidence, widened to nearby sentences if
        # needed, must carry the claim's content words, numbers, and laterality.
        span = span and supported_span(claim.text, span, chunk_text)
        if not span or not normalize_name(claim.concept):
            rejected += 1
            continue
        key = normalize_name(claim.concept)
        if key not in concepts:
            concepts[key] = ExtractedConcept(name=claim.concept, type="other", aliases=[])
        claims.append(claim.model_copy(update={"evidence_span": span}))
    relations = [
        r for r in result.relations
        if normalize_name(r.src) in concepts and normalize_name(r.dst) in concepts
        and normalize_name(r.src) != normalize_name(r.dst)
    ]
    return FilteredExtraction(
        concepts=list(concepts.values()), claims=claims, relations=relations,
        rejected_claims=rejected, rejected_relations=len(result.relations) - len(relations),
    )


def locate_blocks(span: str, blocks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blocks (page_no, block_no, bbox) that carry the span, for bbox provenance.

    A span inside one block cites that block; a span crossing blocks cites every
    block that lies inside the span or whose tail/head overlaps the span's
    head/tail (at least 8 characters). Falls back to all supplied blocks.
    """
    target = collapse_ws(span)

    def overlaps(text: str) -> bool:
        text = collapse_ws(text)
        if len(text) >= MIN_SPAN_CHARS and text in target:
            return True
        for size in range(min(len(text), len(target)), MIN_SPAN_CHARS - 1, -1):
            if target.startswith(text[-size:]) or target.endswith(text[:size]):
                return True
        return False

    def ref(block: dict[str, Any]) -> dict[str, Any]:
        return {"page_no": block["page_no"], "block_no": block["block_no"],
                "bbox": [float(v) for v in block.get("bbox") or []]}

    inside = [b for b in blocks if target in collapse_ws(b["text"])]
    if inside:
        return [ref(inside[0])]
    crossing = [b for b in blocks if overlaps(b["text"])]
    return [ref(b) for b in (crossing or list(blocks))]


def evidence_pages(refs: Sequence[dict[str, Any]], page_from: int, page_to: int) -> tuple[int, int]:
    """The pages the evidence sits on, within the chunk's range; the range itself if unknown."""
    pages = [int(r["page_no"]) for r in refs if page_from <= int(r["page_no"]) <= page_to]
    return (min(pages), max(pages)) if pages else (page_from, page_to)
