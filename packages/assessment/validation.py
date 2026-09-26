"""Deterministic item checks and excerpt-citation resolution (spec section 8, step 3).

The generator only ever sees numbered excerpts (``E1``..``En`` for text chunks,
``F1``.. for figure descriptions). Every id an item cites must be one that was
supplied; the id is then resolved to the excerpt's stored provenance so a
question never carries a citation that points outside the caller's library.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from packages.assessment.models import GeneratedItem

MAX_SBA_STEM_WORDS = 120
SBA_OPTIONS = 5
MIN_VIVA_TURNS = 2
_BANNED_OPTION = re.compile(r"\b(all|none|both) of the (above|following)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Excerpt:
    """One numbered piece of source material shown to the generator."""

    ref: str
    heading: str
    text: str
    citation: dict[str, Any]
    figure_id: UUID | None = None


def render_excerpts(excerpts: Sequence[Excerpt]) -> str:
    """Render excerpts as delimited, id-tagged data blocks for the prompt."""
    blocks = []
    for excerpt in excerpts:
        where = excerpt.citation.get("source_title", "")
        page = excerpt.citation.get("page_from") or excerpt.citation.get("page_no")
        head = f"[{excerpt.ref}] {where} p.{page}" + (
            f" | {excerpt.heading}" if excerpt.heading else "")
        blocks.append(f"<excerpt id=\"{excerpt.ref}\">\n{head}\n{excerpt.text}\n</excerpt>")
    return "\n\n".join(blocks)


def cited_ids(item: GeneratedItem) -> set[str]:
    ids = set(item.citations)
    for option in item.options:
        ids.update(option.citations)
    for point in item.marking_scheme:
        ids.update(point.citations)
    for turn in item.viva_turns:
        ids.update(turn.citations)
    return ids


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _sba_problems(item: GeneratedItem) -> list[str]:
    problems: list[str] = []
    texts = [_norm(option.text) for option in item.options]
    if len(item.options) != SBA_OPTIONS:
        problems.append("sba_requires_five_options")
    elif len(set(texts)) != SBA_OPTIONS or not all(texts):
        problems.append("sba_options_not_distinct")
    if not 0 <= item.key_index < len(item.options):
        problems.append("sba_key_out_of_range")
    elif len(texts[item.key_index]) >= 4 and texts[item.key_index] in _norm(item.stem):
        problems.append("sba_key_repeated_in_stem")
    if any(_BANNED_OPTION.search(option.text) for option in item.options):
        problems.append("sba_all_or_none_of_the_above")
    if len(item.stem.split()) > MAX_SBA_STEM_WORDS:
        problems.append("sba_stem_too_long")
    if any(not option.explanation.strip() or not option.citations for option in item.options):
        problems.append("sba_option_explanation_uncited")
    return problems


def _free_text_problems(item: GeneratedItem) -> list[str]:
    problems: list[str] = []
    if not item.model_answer.strip():
        problems.append("model_answer_missing")
    if not item.marking_scheme:
        problems.append("marking_scheme_missing")
    if item.type == "image_case" and not item.key_findings:
        problems.append("image_case_findings_missing")
    if item.type == "viva" and len(item.viva_turns) < MIN_VIVA_TURNS:
        problems.append("viva_chain_too_short")
    return problems


def check_item(item: GeneratedItem, requested_type: str, supplied: Iterable[str]) -> list[str]:
    """Return deterministic problems; an empty list means the item may be model-checked."""
    problems: list[str] = []
    if item.type != requested_type:
        problems.append("type_mismatch")
    if not item.stem.strip():
        problems.append("stem_missing")
    if not item.citations:
        problems.append("citations_missing")
    unknown = cited_ids(item) - set(supplied)
    if unknown:
        problems.append("citation_not_supplied")
    problems += _sba_problems(item) if item.type == "sba" else _free_text_problems(item)
    return problems


def resolve(ids: Iterable[str], excerpts: Sequence[Excerpt]) -> list[dict[str, Any]]:
    """Map excerpt ids to stored provenance, preserving first-seen order."""
    by_ref = {excerpt.ref: excerpt for excerpt in excerpts}
    seen: list[str] = []
    for ref in ids:
        if ref not in by_ref:
            raise KeyError("citation was not supplied")
        if ref not in seen:
            seen.append(ref)
    return [{"ref": ref, **by_ref[ref].citation} for ref in seen]


def figure_for(item: GeneratedItem, excerpts: Sequence[Excerpt]) -> UUID | None:
    refs = cited_ids(item)
    return next((e.figure_id for e in excerpts if e.ref in refs and e.figure_id), None)


def stored_parts(item: GeneratedItem, excerpts: Sequence[Excerpt]) -> dict[str, Any]:
    """Split a checked item into the persisted options, answer, and citations."""
    options = [
        {"text": o.text, "explanation": o.explanation, "citations": resolve(o.citations, excerpts)}
        for o in item.options
    ]
    answer: dict[str, Any]
    if item.type == "sba":
        answer = {"key": item.key_index}
    else:
        answer = {
            "model_answer": item.model_answer,
            "marking_scheme": [
                {"point": p.point, "marks": p.marks, "citations": resolve(p.citations, excerpts)}
                for p in item.marking_scheme
            ],
            "key_findings": item.key_findings,
            "viva_turns": [
                {"question": t.question, "expected_answer": t.expected_answer,
                 "citations": resolve(t.citations, excerpts)}
                for t in item.viva_turns
            ],
        }
    return {
        "options": options,
        "answer": answer,
        "citations": resolve(item.citations, excerpts),
        "figure_id": figure_for(item, excerpts),
    }
