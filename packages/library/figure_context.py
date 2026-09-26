"""Anchor figure diagnoses to the owner's own pages (ADR 0036).

Exam decks put the image on one slide and the answer on the next, so the
``image_case`` agent (v2) reads a figure together with the text of its page and
the page after it. Wider context was tried and rejected: two pages on, the next
case's answer slide was taken as this image's diagnosis.

A diagnosis counts as the source's only when the agent returns a verbatim quote
that is really in that text; anything else is kept as an unverified model
opinion and is never used as evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Literal

from packages.library.parse_models import ImageCase, SourceImageCase
from packages.models.gateway import soft

PAGES_AFTER = 1  # the answer slide; earlier or later pages belong to other cases
PAGE_CHARS = 2500
CONTEXT_CHARS = 10000
Origin = Literal["source", "model"]

UNVERIFIED = "Impression (unverified model opinion)"
_FOLD = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                       "\u2013": "-", "\u2014": "-", "\u00a0": " "})
_WORD = re.compile(r"[a-z0-9]+")


def neighbour_pages(page_no: int) -> tuple[int, int]:
    return page_no, page_no + PAGES_AFTER


def build_context(page_no: int, texts: Mapping[int, str]) -> str:
    """This page first, then the nearest neighbours, each clipped, labelled by page."""
    order = sorted(texts, key=lambda n: (abs(n - page_no), n))
    parts: list[str] = []
    used = 0
    for number in order:
        body = " ".join((texts[number] or "").split())[:PAGE_CHARS]
        if not body:
            continue
        label = "this page" if number == page_no else f"page {number}"
        part = f"[{label}] {body}"
        if used + len(part) > CONTEXT_CHARS:
            break
        parts.append(part)
        used += len(part)
    return "\n".join(parts) or "(no text on this page or its neighbours)"


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).translate(_FOLD).lower()
    return _WORD.findall(folded)


def quote_in_context(quote: str, context: str) -> bool:
    """True when the quote's words occur, in order and adjacent, in the context."""
    if quote.strip().endswith("?"):
        return False  # a question never states the answer
    words = _words(quote)
    return bool(words) and f" {' '.join(words)} " in f" {' '.join(_words(context))} "


def impression_origin(case: SourceImageCase, context: str) -> tuple[Origin, str | None]:
    """``source`` with its quote only when the quote is verifiably in the context."""
    if (case.impression.strip() and case.impression_source == "source"
            and quote_in_context(case.source_quote, context)):
        return "source", case.source_quote.strip()
    return "model", None


def figure_problem(case: SourceImageCase, context: str) -> str | None:
    """Quality gate for a figure reading (ADR 0037): why Sol should look again, or None.

    A reading that sees nothing, or that cites the page for a diagnosis the page
    does not state, goes on to Sol (and, if Sol fails too, to the owner). A
    low-confidence impression only asks Sol for a second opinion.
    """
    if not case.findings and not case.impression.strip():
        return "empty_reading"
    if case.impression_source == "source" and not quote_in_context(case.source_quote, context):
        return "unverified_source_quote"
    if case.impression.strip() and case.confidence == "low":
        return soft("low_confidence")
    return None


def case_text(case: ImageCase, origin: Origin | None = None) -> str:
    """The stored figure description; a model-only impression is labelled as such."""
    parts = [f"Findings: {'; '.join(case.findings)}" if case.findings else ""]
    if case.impression:
        label = {"source": "Impression (stated in the source)",
                 "model": UNVERIFIED}.get(origin or "", "Impression")
        parts.append(f"{label}: {case.impression} (confidence {case.confidence})")
    if case.differentials:
        parts.append(f"Differentials: {', '.join(case.differentials)}")
    if case.teaching_points:
        parts.append(f"Teaching points: {'; '.join(case.teaching_points)}")
    return "\n".join(p for p in parts if p)


def evidence_description(description: str | None) -> str:
    """A figure description fit to cite: the unverified model impression is dropped."""
    lines = (description or "").splitlines()
    return "\n".join(line for line in lines if not line.startswith(UNVERIFIED)).strip()
