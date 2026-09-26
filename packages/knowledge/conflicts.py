"""Claim duplicate and contradiction heuristics (spec section 5).

Two claims about the same concept are compared only when their content words
overlap strongly (high topical overlap). Such a pair is then:

* a duplicate when the statements are near-identical (trigram >= 0.90): the
  second source is appended as supporting evidence instead of a new claim;
* a conflict when they disagree on a number with the same unit, on negation,
  or on an opposed term pair (hyper/hypo, left/right, ...). A conflict becomes
  an explicit ``knowledge_conflicts`` row and both claims are marked
  ``disputed``; neither claim is overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packages.knowledge.text import normalize_name, trigram_similarity

DUPLICATE = 0.90
OVERLAP = 0.5

_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?")
_NUMBER = re.compile(
    r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(%|mm|cm|m|hu|ml|mg|kg|kev|kv|ma|msv|mgy|gy|t|hz|"
    r"mhz|mmhg|years?|yrs?|y|months?|weeks?|wks?|days?|hours?|hrs?|minutes?|mins?|"
    r"seconds?|s|ms)?(?![a-z])"
)
_NEGATIONS = frozenset({
    "no", "not", "never", "without", "absent", "absence", "none", "cannot", "non",
    "neither", "nor", "lacks", "lack", "isnt", "doesnt", "dont", "arent", "rarely",
})
_OPPOSED: tuple[tuple[str, str], ...] = (
    ("hyperintense", "hypointense"), ("hyperdense", "hypodense"),
    ("hyperechoic", "hypoechoic"), ("hyperattenuating", "hypoattenuating"),
    ("increased", "decreased"), ("increase", "decrease"), ("high", "low"),
    ("left", "right"), ("unilateral", "bilateral"), ("upper", "lower"),
    ("anterior", "posterior"), ("medial", "lateral"), ("proximal", "distal"),
    ("central", "peripheral"), ("benign", "malignant"), ("common", "rare"),
    ("early", "late"), ("acute", "chronic"), ("restricted", "facilitated"),
    ("enhancing", "nonenhancing"), ("calcified", "noncalcified"),
    ("males", "females"), ("male", "female"), ("children", "adults"),
)
_OPPOSED_WORDS = frozenset(word for pair in _OPPOSED for word in pair)
_STOP = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "to", "is", "are", "was", "be", "with",
    "and", "or", "by", "for", "as", "it", "its", "this", "that", "from", "may", "can",
    "seen", "usually", "typically", "often", "most", "more", "than", "which", "also",
})
_UNIT_ALIASES = {"year": "years", "yrs": "years", "yr": "years", "y": "years",
                 "month": "months", "week": "weeks", "wks": "weeks", "day": "days",
                 "hour": "hours", "hrs": "hours", "minute": "minutes", "mins": "minutes",
                 "second": "seconds", "s": "seconds"}


@dataclass(frozen=True, slots=True)
class Verdict:
    kind: str  # "duplicate" | "numeric" | "negation" | "opposite_terms"
    description: str


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("'", "").replace("-", ""))


def content_words(text: str) -> set[str]:
    return {
        w for w in _words(text)
        if w not in _STOP and w not in _NEGATIONS and w not in _OPPOSED_WORDS
        and not re.fullmatch(r"[0-9.]+%?", w)
    }


def topical_overlap(left: str, right: str) -> float:
    a, b = content_words(left), content_words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def numbers(text: str) -> dict[str, set[float]]:
    """Numbers grouped by unit ('' for unitless)."""
    found: dict[str, set[float]] = {}
    for value, unit in _NUMBER.findall(text.lower()):
        key = _UNIT_ALIASES.get(unit, unit)
        found.setdefault(key, set()).add(float(value))
    return found


def _negated(text: str) -> bool:
    return any(word in _NEGATIONS for word in _words(text))


def _numeric_disagreement(left: str, right: str) -> str | None:
    a, b = numbers(left), numbers(right)
    for unit in sorted(set(a) & set(b)):
        if unit and a[unit].isdisjoint(b[unit]):
            values = f"{sorted(a[unit])} vs {sorted(b[unit])}"
            return f"Numeric disagreement ({unit}): {values}"
    return None


def _opposed_terms(left: str, right: str) -> str | None:
    a, b = set(_words(left)), set(_words(right))
    for first, second in _OPPOSED:
        if (first in a and second in b and second not in a and first not in b) or (
            second in a and first in b and first not in a and second not in b
        ):
            return f"Opposed terms: {first} vs {second}"
    return None


def compare_claims(left: str, right: str) -> Verdict | None:
    """Classify a same-concept claim pair; None when unrelated or compatible."""
    if trigram_similarity(normalize_name(left), normalize_name(right)) >= DUPLICATE:
        numeric = _numeric_disagreement(left, right)
        if numeric is None and _negated(left) == _negated(right):
            return Verdict("duplicate", "Near-identical statement")
    if topical_overlap(left, right) < OVERLAP:
        return None
    numeric = _numeric_disagreement(left, right)
    if numeric is not None:
        return Verdict("numeric", numeric)
    if _negated(left) != _negated(right):
        return Verdict("negation", "One statement negates the other")
    opposed = _opposed_terms(left, right)
    if opposed is not None:
        return Verdict("opposite_terms", opposed)
    return None
