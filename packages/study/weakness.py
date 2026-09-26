"""Weakness loop rules (spec section 7): a wrong answer re-tests within two days.

A wrong SBA answer (practice, Today session, or a submitted exam) creates a
recall card for that question, citing the chunk the question cites, or resets
the card made for it earlier; either way the card is due again after
``WEAKNESS_DELAY``, well inside the two-day window, and the question is queued
for a re-test in the next session's SBA block. A card rated Again already
relearns in minutes (FSRS), so a lapse only queues a re-test of a question on
the same chunk. Every event is keyed by the attempt or review it came from, so
recording it twice changes nothing. Plain code, no model call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

WEAKNESS_DELAY = timedelta(days=1)
RETEST_WINDOW = timedelta(days=2)
FALLBACK_CODE = "UNMAPPED"
FRONT_MAX = 2000
BACK_MAX = 4000
TOPIC_MAX = 200
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")

WeaknessKind = Literal["sba_wrong", "exam_wrong", "card_lapse"]


def is_wrong(score: float, max_score: float) -> bool:
    return max_score > 0 and score < max_score


def due_at(now: datetime) -> datetime:
    return now + WEAKNESS_DELAY


def retest_by(now: datetime) -> datetime:
    return now + RETEST_WINDOW


def card_code(code: str | None) -> str:
    """A card needs a code; an unmapped question's card is labelled ``UNMAPPED``."""
    return code if code and _CODE.match(code) and len(code) <= 64 else FALLBACK_CODE


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _key_text(question: Mapping[str, Any]) -> str:
    options = list(question.get("options") or [])
    key = (question.get("answer") or {}).get("key")
    if isinstance(key, int) and 0 <= key < len(options):
        return str(options[key].get("text", ""))
    return str((question.get("answer") or {}).get("model_answer", ""))


def card_text(question: Mapping[str, Any], chunk_heading: str = "") -> dict[str, str]:
    """Front, back and topic of the weakness card for ``question``."""
    front = _clip(str(question.get("stem", "")), FRONT_MAX) or "Review this item."
    key = _key_text(question)
    explanation = str(question.get("explanation", ""))
    back = _clip(f"{key}. {explanation}" if explanation else key, BACK_MAX) or front
    topic = _clip(str(question.get("topic") or chunk_heading or "Weak item"), TOPIC_MAX)
    return {"front": front, "back": back, "topic": topic or "Weak item"}


def first_chunk_id(citations: Any) -> str | None:
    """The first chunk a question cites (assessment citations: kind chunk|figure)."""
    for citation in citations or []:
        if isinstance(citation, Mapping) and citation.get("kind") == "chunk":
            value = citation.get("chunk_id")
            if isinstance(value, str) and value:
                return value
    return None
