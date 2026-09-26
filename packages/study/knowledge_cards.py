"""Cloze cards from verified claims and image cards from described figures (ADR 0029).

Plain code, no model call. A **cloze** card blanks the key term of a claim the
knowledge pipeline stored with a verbatim evidence span: the claim's concept
name or one of its aliases when the statement names it, else a measurement
(number and unit). A claim with no such term is skipped rather than blanked
arbitrarily. The card cites the claim's evidence: source, pages, and the
blocks that hold the span. An **image** card shows a described figure and asks
for the finding or diagnosis; its answer is the figure's own caption, findings,
and description, cited to the figure (source, page, bounding box). Fail closed:
anything without a resolvable citation yields no card.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from packages.study.weakness import FALLBACK_CODE

BLANK = "_____"
FRONT_MAX = 2000
BACK_MAX = 4000
TOPIC_MAX = 200
MIN_TERM_CHARS = 3
MIN_CONTEXT_WORDS = 3
_UNIT = (r"(?:mm|cm|m|%|HU|ms|mSv|Gy|MHz|kHz|T|kg|g|mg|ml|mL|L|cc|years?|months?|weeks?"
         r"|days?|hours?|minutes?|seconds?|degrees?|°)")
_MEASURE = re.compile(rf"\b\d+(?:\.\d+)?(?:\s?(?:-|–|to)\s?\d+(?:\.\d+)?)?\s?{_UNIT}(?!\w)")


def _clip(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _term_pattern(term: str) -> re.Pattern[str]:
    words = [re.escape(word) for word in term.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", re.IGNORECASE)


def key_term(statement: str, names: Iterable[str]) -> str | None:
    """The span of ``statement`` to blank: the longest named term, else a measurement."""
    for name in sorted({" ".join(n.split()) for n in names if n}, key=len, reverse=True):
        if len(name) < MIN_TERM_CHARS:
            continue
        found = _term_pattern(name).search(statement)
        if found:
            return found.group(0)
    measure = _MEASURE.search(statement)
    return measure.group(0) if measure else None


def blank(statement: str, term: str) -> str | None:
    """Blank every occurrence of ``term``; None when too little context is left."""
    front = _term_pattern(term).sub(BLANK, statement)
    context = front.replace(BLANK, " ").split()
    return front if BLANK in front and len(context) >= MIN_CONTEXT_WORDS else None


def card_code(code: str | None, systems: Collection[str]) -> str:
    """The card's curriculum system: the node's system when known, else ``UNMAPPED``."""
    system = str(code or "").split(".")[0]
    return system if system in systems else FALLBACK_CODE


def claim_citation(claim: Mapping[str, Any]) -> dict[str, Any] | None:
    """Source, pages, and the blocks holding the claim's evidence span."""
    stored = dict(claim.get("citation") or {})
    source_id = str(claim.get("source_id") or stored.get("source_id") or "")
    if not source_id or claim.get("page_from") is None:
        return None
    refs = [{"page": int(b["page_no"]), "block": int(b["block_no"])}
            for b in stored.get("blocks") or [] if "page_no" in b and "block_no" in b]
    return {"kind": "claim", "claim_id": str(claim["id"]), "source_id": source_id,
            "source_title": str(claim.get("source_title") or stored.get("source_title") or ""),
            "chunk_id": str(claim["chunk_id"]) if claim.get("chunk_id") else None,
            "page_from": int(claim["page_from"]),
            "page_to": int(claim.get("page_to") or claim["page_from"]),
            "block_refs": refs}


def cloze_card(claim: Mapping[str, Any], systems: Collection[str]) -> dict[str, Any] | None:
    """A cloze card for one claim, or None when it has no blankable term or citation."""
    statement = " ".join(str(claim["statement"]).split())
    names = [str(claim.get("concept_name") or ""), *(claim.get("aliases") or [])]
    term = key_term(statement, names)
    citation = claim_citation(claim)
    if term is None or citation is None:
        return None
    front = blank(statement, term)
    if front is None:
        return None
    back = (f"{term}\n\n{statement}\n\nEvidence: “"
            f"{' '.join(str(claim['evidence_span']).split())}”")
    return {"source_id": claim["source_id"], "source_chunk_id": claim.get("chunk_id"),
            "curriculum_code": card_code(claim.get("concept_code") or claim.get("mapped_code"),
                                         systems),
            "topic": _clip(str(claim.get("concept_name") or "Claim"), TOPIC_MAX),
            "front": _clip(front, FRONT_MAX), "back": _clip(back, BACK_MAX),
            "origin": "claim", "card_type": "cloze", "claim_id": claim["id"],
            "figure_id": None, "citation": citation}


def figure_citation(figure: Mapping[str, Any]) -> dict[str, Any] | None:
    if figure.get("page_no") is None or not figure.get("source_id"):
        return None
    page = int(figure["page_no"])
    return {"kind": "figure", "figure_id": str(figure["id"]),
            "source_id": str(figure["source_id"]),
            "source_title": str(figure.get("source_title") or ""),
            "page_from": page, "page_to": page, "block_refs": [],
            "bbox": [float(v) for v in figure.get("bbox") or []]}


def _figure_hint(figure: Mapping[str, Any]) -> str:
    parts = [str(figure.get("modality") or "").strip(), str(figure.get("anatomy") or "").strip()]
    hint = " ".join(p for p in parts if p)
    return f" ({hint})" if hint else ""


def image_card(figure: Mapping[str, Any], systems: Collection[str]) -> dict[str, Any] | None:
    """An image card for one described figure, or None without a description or citation."""
    description = " ".join(str(figure.get("description") or "").split())
    citation = figure_citation(figure)
    if not description or citation is None:
        return None
    findings = [str(f).strip() for f in figure.get("findings") or [] if str(f).strip()]
    caption = " ".join(str(figure.get("caption") or "").split())
    back = "\n\n".join(part for part in (
        caption, "Findings: " + "; ".join(findings) if findings else "", description) if part)
    return {"source_id": figure["source_id"], "source_chunk_id": None,
            "curriculum_code": card_code(figure.get("mapped_code"), systems),
            "topic": _clip(caption or str(figure.get("anatomy") or "Image"), TOPIC_MAX),
            "front": f"Name the key finding and the most likely diagnosis{_figure_hint(figure)}.",
            "back": _clip(back, BACK_MAX), "origin": "figure", "card_type": "image",
            "claim_id": None, "figure_id": figure["id"], "citation": citation}
