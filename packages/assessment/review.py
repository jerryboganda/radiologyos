"""Owner review of draft questions: edits, re-checks, and citation references.

Edits change wording only; citations are never editable, so every edited item
still points at the excerpts it was generated from. After an edit the same
deterministic item checks run again on the stored shape, and approval requires
every cited source page and figure to still exist in a non-deleted source.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from packages.assessment.validation import MAX_SBA_STEM_WORDS, SBA_OPTIONS

_BANNED = re.compile(r"\b(all|none|both) of the (above|following)\b", re.IGNORECASE)
EDITABLE = ("stem", "topic", "explanation", "options", "key_index", "model_answer")


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def apply_edits(question: Mapping[str, Any], edits: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``question`` with the given wording edits applied."""
    updated = {**question, "answer": dict(question["answer"]),
               "options": [dict(o) for o in question["options"]]}
    for field in ("stem", "topic", "explanation"):
        if edits.get(field) is not None:
            updated[field] = edits[field]
    if edits.get("options") is not None:
        texts = list(edits["options"])
        if len(texts) != len(updated["options"]):
            raise ValueError("options_count_changed")
        for option, text in zip(updated["options"], texts, strict=True):
            option["text"] = text
    if edits.get("key_index") is not None:
        updated["answer"]["key"] = int(edits["key_index"])
    if edits.get("model_answer") is not None:
        updated["answer"]["model_answer"] = edits["model_answer"]
    return updated


def stored_problems(question: Mapping[str, Any]) -> list[str]:
    """Deterministic checks on a stored (edited) item; [] means it may be approved."""
    problems: list[str] = []
    if not str(question["stem"]).strip():
        problems.append("stem_missing")
    if not question.get("citations"):
        problems.append("citations_missing")
    if question["type"] != "sba":
        if not str(question["answer"].get("model_answer", "")).strip():
            problems.append("model_answer_missing")
        if not question["answer"].get("marking_scheme"):
            problems.append("marking_scheme_missing")
        return problems
    texts = [_norm(o["text"]) for o in question["options"]]
    if len(texts) != SBA_OPTIONS or len(set(texts)) != SBA_OPTIONS or not all(texts):
        problems.append("sba_options_not_distinct")
    key = int(question["answer"].get("key", -1))
    if not 0 <= key < len(texts):
        problems.append("sba_key_out_of_range")
    elif len(texts[key]) >= 4 and texts[key] in _norm(question["stem"]):
        problems.append("sba_key_repeated_in_stem")
    if any(_BANNED.search(o["text"]) for o in question["options"]):
        problems.append("sba_all_or_none_of_the_above")
    if len(str(question["stem"]).split()) > MAX_SBA_STEM_WORDS:
        problems.append("sba_stem_too_long")
    return problems


def _citation_lists(question: Mapping[str, Any]) -> Iterable[list[dict[str, Any]]]:
    yield question.get("citations") or []
    for option in question.get("options") or []:
        yield option.get("citations") or []
    answer = question.get("answer") or {}
    for point in answer.get("marking_scheme") or []:
        yield point.get("citations") or []
    for turn in answer.get("viva_turns") or []:
        yield turn.get("citations") or []


def cited_targets(question: Mapping[str, Any]) -> tuple[set[tuple[UUID, int]], set[UUID]]:
    """((source id, page) pairs, figure ids) referenced anywhere in a stored question.

    Chunk ids are not used: re-chunking after the vision pass replaces them,
    while the cited source page stays a stable provenance anchor.
    """
    pages: set[tuple[UUID, int]] = set()
    figures: set[UUID] = set()
    for citations in _citation_lists(question):
        for citation in citations:
            try:
                if citation.get("kind") == "figure":
                    figures.add(UUID(str(citation["figure_id"])))
                else:
                    pages.add((UUID(str(citation["source_id"])), int(citation["page_from"])))
            except (KeyError, TypeError, ValueError):
                pages.add((UUID(int=0), 0))  # unresolvable: never valid
    return pages, figures


def checker_reasons(quality: Mapping[str, Any]) -> list[str]:
    check = quality.get("check") or {}
    if "error" in check:
        return ["checker_error"]
    return [str(r) for r in check.get("reasons") or []] or (
        [] if quality.get("passed") else ["checker_failed"])
