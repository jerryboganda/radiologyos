"""Deterministic question-intent routing for the tutor (ADR 0028).

A cheap keyword/regex classifier; no model call. The intent steers retrieval
(both subjects of a comparison, figure-first for "show me", differential
edges for a DDx) and the answer's shape (``tutor_answer`` v4), while the
citation rules never change. ``quiz`` hands the topic to question generation
instead of answering. Precedence: quiz > report > compare > show_me > ddx >
explain, so "compare the DDx of A vs B" is a comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Intent = Literal["explain", "compare", "ddx", "show_me", "report", "quiz"]
INTENTS: tuple[Intent, ...] = ("explain", "compare", "ddx", "show_me", "report", "quiz")
MAX_SUBJECT_CHARS = 120

_I = re.IGNORECASE
_QUIZ = re.compile(
    r"\b(quiz|test) me\b|\bask me (some |a few |\d+ )?questions?\b"
    r"|\b(give|make|generate|write) me\b.{0,20}\b(mcqs?|sbas?|questions?|flash ?cards?)\b"
    r"|\b(mcqs?|sbas?)\s+(on|about|for)\b", _I)
_REPORT = re.compile(
    r"\bstructured report|\breport(ing)? (template|format|checklist)"
    r"|\bhow (do|would|should|to) (i |you |we )?report\b|\b(write|dictate|draft)\b.{0,20}"
    r"\breport\b|\breport (for|of|on) (a|an|this|the)\b", _I)
_COMPARE = re.compile(
    r"\bvs\.?\s|\bversus\b|\bcompare\b|\bcomparison\b|\bcontrast\b"
    r"|\b(difference|differences|distinguish|differentiate|tell apart)\b.{0,40}\bbetween\b"
    r"|\bhow (do|does|can) .{2,60} differ", _I)
_SHOW = re.compile(
    r"\bshow me\b|\bwhat does .{2,80} look like\b|\b(images?|pictures?|figures?|examples?)"
    r" (of|showing)\b|\bexample (image|case|film)s?\b|\bspotters?\b", _I)
_DDX = re.compile(
    r"\bddx\b|\bdifferentials?\b|\bdifferential diagnos[ie]s\b|\bwhat could (this|it|these)"
    r" be\b|\bcauses of\b|\bd/d\b|\b\d{1,3}[- ]?(y|yo|yr|year)s?[- ]old\b", _I)
_SPLIT_VS = re.compile(r"\s+(?:vs\.?|versus|compared (?:to|with)|and)\s+", _I)
_BETWEEN = re.compile(r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:[?.!,;]|\s+on\s|\s+in\s|$)", _I)
_LEAD = re.compile(
    r"^.*?\b(compare|contrast|comparison of|difference of|differentiate|distinguish)\s+", _I)
_TRAIL = re.compile(r"\s+(on|in|at|with|for)\s+(ct|mri?|us|ultrasound|x-?ray|imaging|"
                    r"radiographs?|pet)\b.*$|[?.!]+$", _I)


@dataclass(frozen=True, slots=True)
class Route:
    intent: Intent
    subjects: tuple[str, ...] = ()

    @property
    def topic(self) -> str:
        return "; ".join(self.subjects)


def _clean(part: str) -> str:
    part = _TRAIL.sub("", part.strip(" \t\n,;:?.!\"'"))
    part = re.sub(r"^(the|a|an)\s+", "", part.strip(), flags=_I)
    return part.strip()[:MAX_SUBJECT_CHARS]


def compare_subjects(question: str) -> tuple[str, ...]:
    """The two things being compared, when the wording names them; else ()."""
    between = _BETWEEN.search(question)
    if between:
        parts = [between.group(1), between.group(2)]
    else:
        body = _LEAD.sub("", question.strip())
        pieces = _SPLIT_VS.split(body, maxsplit=1)
        if len(pieces) != 2:
            return ()
        parts = pieces
    subjects = tuple(p for p in (_clean(p) for p in parts) if len(p) >= 2)
    return subjects if len(subjects) == 2 and subjects[0].lower() != subjects[1].lower() else ()


def quiz_topic(question: str) -> str:
    """The topic to quiz on: the text after "on/about/for", else the whole question."""
    match = re.search(r"\b(?:on|about|for|regarding)\s+(.+)$", question.strip(), _I)
    topic = _clean(match.group(1)) if match else _clean(question)
    return topic[:MAX_SUBJECT_CHARS]


def classify_intent(question: str) -> Route:
    """The question's intent (and subjects for compare, topic for quiz)."""
    q = " ".join(question.split())
    if _QUIZ.search(q):
        topic = quiz_topic(q)
        return Route("quiz", (topic,) if len(topic) >= 2 else ())
    if _REPORT.search(q):
        return Route("report")
    if _COMPARE.search(q):
        return Route("compare", compare_subjects(q))
    if _SHOW.search(q):
        return Route("show_me")
    if _DDX.search(q):
        return Route("ddx")
    return Route("explain")
