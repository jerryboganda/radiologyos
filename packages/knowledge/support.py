"""Does the evidence span actually support the claim? (ADR 0037, "over-reach").

A span that is verbatim in the chunk can still be too short for its claim, e.g.
"Elevation of both fat pads signifies an underlying fracture" backed only by
"This signifies an underlying fracture,". The check compares the claim's
content words and numbers with the span's. When they fall short, the span is
widened to the whole sentence and then to its neighbouring sentences - still a
verbatim part of the chunk - and the claim keeps the smallest span that
supports it. A claim nothing nearby supports is over-reach and is rejected.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from packages.knowledge.text import collapse_ws

MIN_SUPPORT = 0.6  # share of the claim's content words the evidence must contain
MAX_WIDEN = 2  # sentences added on each side, at most
NEAR = 0.9  # spelling similarity that still counts as the same word
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_EXACT = frozenset((
    "left", "right", "bilateral", "unilateral", "anterior", "posterior", "medial", "lateral",
    "superior", "inferior", "proximal", "distal", "not", "no", "never", "without", "absent",
))
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")
_STOP = frozenset((
    "this", "that", "these", "those", "with", "from", "into", "than", "then", "there",
    "their", "they", "them", "were", "have", "been", "being", "which", "what", "when",
    "where", "while", "also", "most", "more", "such", "some", "other", "another", "about",
    "does", "done", "each", "only", "over", "very", "will", "would", "should", "could",
    "shows", "show", "seen", "identified", "described", "represents", "present",
    # Framing words a claim adds to name what the source is talking about.
    "image", "taken", "study", "examination", "diagnosis", "finding", "noted", "patient",
))


def _stem(word: str) -> str:
    """British/American spelling folded (haemorrhage, oedema), light suffix stripping."""
    word = word.replace("ae", "e").replace("oe", "e")
    for suffix, keep in (("ies", "y"), ("ing", ""), ("s", "")):
        if word.endswith(suffix) and not word.endswith("ss") and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)] + keep
    return word


def content_words(text: str, pairs: bool = False) -> set[str]:
    """Stemmed content words; with ``pairs`` also joined neighbours ("horse shoe")."""
    raw = re.findall(r"[a-z]+", text.lower())
    words = {w for w in raw if len(w) >= 4}
    if pairs:
        words |= {a + b for a, b in zip(raw, raw[1:], strict=False) if len(a + b) >= 4}
    return {_stem(w) for w in words if w not in _STOP}


def supports(statement: str, evidence: str) -> bool:
    """The evidence carries the claim's numbers and most of its content words."""
    if not set(_NUMBER.findall(statement)) <= set(_NUMBER.findall(evidence)):
        return False
    said = set(re.findall(r"[a-z]+", evidence.lower()))
    if not {w for w in re.findall(r"[a-z]+", statement.lower()) if w in _EXACT} <= said:
        return False  # laterality, position, and negation are never inferred
    words = content_words(statement)
    if not words:
        return True
    have = content_words(evidence, pairs=True)
    found = sum(1 for w in words if w in have or _near(w, have))
    return found / len(words) >= MIN_SUPPORT


def _near(word: str, have: set[str]) -> bool:
    """A source typo still counts ("inracerebral" for "intracerebral")."""
    return len(word) >= 6 and any(
        abs(len(word) - len(h)) <= 2 and SequenceMatcher(None, word, h).ratio() >= NEAR
        for h in have)


def supported_span(statement: str, span: str, chunk_text: str) -> str | None:
    """The smallest verbatim evidence around ``span`` that supports the claim, or None."""
    if supports(statement, span):
        return span
    text = collapse_ws(chunk_text)
    start = text.find(collapse_ws(span))
    if start < 0:
        return None
    sentences = _sentences(text)
    first = last = _index(sentences, start)
    end_index = _index(sentences, start + len(collapse_ws(span)) - 1)
    last = max(last, end_index)
    for step in range(MAX_WIDEN + 1):
        lo, hi = max(0, first - step), min(len(sentences) - 1, last + step)
        for a, b in ((lo, last), (first, hi), (lo, hi)):
            candidate = text[sentences[a][0]:sentences[b][1]].strip()
            if supports(statement, candidate):
                return candidate
    return None


def _sentences(text: str) -> list[tuple[int, int]]:
    bounds, begin = [], 0
    for match in _SENTENCE_END.finditer(text):
        bounds.append((begin, match.start()))
        begin = match.end()
    bounds.append((begin, len(text)))
    return bounds


def _index(sentences: list[tuple[int, int]], offset: int) -> int:
    for n, (a, b) in enumerate(sentences):
        if a <= offset <= b:
            return n
    return len(sentences) - 1


_DEICTIC = re.compile(
    r"^\s*(?:(?:the|this|these)\s+(?:diagnosis|image|images|lesion|finding|findings|"
    r"examination|study|procedure|film|view|case|patient)|it|this)\b", re.IGNORECASE)


def context_free(statement: str) -> bool:
    """A claim that leans on the slide ("The diagnosis is X") instead of naming its subject."""
    return _DEICTIC.match(statement) is not None
