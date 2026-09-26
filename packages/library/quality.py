"""Quality gates for model outputs (ADR 0027, owner's "no lapses" rule).

Each gate returns a short reason when an output is not good enough, or None.
The gateway then moves on to the next, stronger target, so a weak answer from
the free tier is redone by Claude rather than silently kept. Reasons are fixed
strings: they never contain source text (hard rule 4).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

MIN_NATIVE_WORDS = 25  # below this the native layer is too thin to judge coverage
MIN_COVERAGE = 0.8  # share of the page's own words the reading must capture
MIN_EVIDENCE_CLAIMS = 4
MAX_REJECTED_SHARE = 0.3  # of claims whose evidence is not in the chunk text
_WORD = re.compile(r"[a-z0-9]{3,}")


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def bbox_ok(bbox: Sequence[float]) -> bool:
    if len(bbox) != 4 or any(not 0.0 <= v <= 1.0 for v in bbox):
        return False
    x0, y0, x1, y1 = bbox
    return x0 < x1 and y0 < y1


def page_parse_problem(parsed: Any, native_text: str | None) -> str | None:
    """Reject a page reading with invalid boxes, or one that misses the page's own text."""
    if any(not bbox_ok(b.bbox) for b in parsed.blocks) or any(
        not bbox_ok(f.bbox) for f in parsed.figures
    ):
        return "bbox_out_of_range"
    native = words(native_text or "")
    if len(native) < MIN_NATIVE_WORDS:
        return None
    read = words(" ".join(b.text for b in parsed.blocks))
    if not read:
        return "empty_reading_of_text_page"
    if len(native & read) / len(native) < MIN_COVERAGE:
        return "low_text_coverage"
    return None


def extraction_problem(rejected_claims: int, kept_claims: int) -> str | None:
    """Reject an extraction whose claims too often lack evidence in the chunk."""
    total = rejected_claims + kept_claims
    if total >= MIN_EVIDENCE_CLAIMS and rejected_claims / total > MAX_REJECTED_SHARE:
        return "unsupported_claims"
    return None
