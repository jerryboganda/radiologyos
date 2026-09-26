"""Deterministic grading and the exam state machine (no model calls).

SBA items are graded by exact match against the stored key. Free-text grades
from the ``seq_grade`` agent are normalised here against the frozen marking
scheme: one result per scheme point, marks clamped to the point's weight, and
no credit for anything outside the scheme. Exams are timed server-side and
autosave with revision compare-and-set; submission is idempotent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from packages.assessment.models import SeqGrade

MAX_TEXT_CHARS = 8000


class ExamError(Exception):
    """Base class; ``code`` is a stable, content-free identifier for the API."""

    code = "exam_error"


class ExamClosed(ExamError):
    code = "exam_submitted"


class ExamExpired(ExamError):
    code = "exam_time_expired"


class StaleRevision(ExamError):
    code = "stale_revision"


class InvalidAnswer(ExamError):
    code = "invalid_answer"


def grade_sba(question: Mapping[str, Any], selected: int | None) -> dict[str, Any]:
    key = int(question["answer"]["key"])
    options = question["options"]
    if selected is not None and not 0 <= selected < len(options):
        raise InvalidAnswer("selected option is out of range")
    correct = selected == key
    return {
        "question_id": str(question["id"]),
        "topic": question.get("topic", ""),
        "selected_option": selected,
        "key": key,
        "correct": correct,
        "score": 1.0 if correct else 0.0,
        "max_score": 1.0,
        "explanation": question.get("explanation", ""),
        "option_explanations": [
            {"text": o["text"], "explanation": o["explanation"], "citations": o["citations"]}
            for o in options
        ],
        "citations": question["citations"],
    }


def apply_seq_grade(scheme: Sequence[Mapping[str, Any]], grade: SeqGrade) -> dict[str, Any]:
    """Normalise a model grade against the frozen scheme; the scheme is authoritative."""
    first: dict[int, Any] = {}
    for point in grade.points:
        if 0 <= point.scheme_index < len(scheme):
            first.setdefault(point.scheme_index, point)
    points = []
    for index, item in enumerate(scheme):
        marks = float(item["marks"])
        result = first.get(index)
        status = result.status if result is not None else "missed"
        awarded = 0.0 if status == "missed" or result is None else min(result.awarded, marks)
        points.append({
            "point": item["point"],
            "marks": marks,
            "awarded": round(awarded, 2),
            "status": status,
            "justification": result.justification if result is not None else "",
            "citations": item["citations"],
            **({"stage": item["stage"]} if item.get("stage") else {}),
        })
    score = round(sum(p["awarded"] for p in points), 2)
    return {"points": points, "score": score,
            "max_score": round(sum(p["marks"] for p in points), 2), "feedback": grade.feedback}


@dataclass(slots=True)
class ExamState:
    mode: str
    question_ids: list[UUID]
    deadline_at: datetime | None
    submitted_at: datetime | None
    revision: int
    answers: dict[str, int] = field(default_factory=dict)
    text_answers: dict[str, str] = field(default_factory=dict)
    free_text_ids: frozenset[str] = frozenset()
    item_seconds: dict[str, int] = field(default_factory=dict)
    confidence: dict[str, int] = field(default_factory=dict)


def exam_status(exam: ExamState, now: datetime) -> str:
    if exam.submitted_at is not None:
        return "submitted"
    if exam.deadline_at is not None and now >= exam.deadline_at:
        return "expired"
    return "active"


def autosave(
    exam: ExamState, revision: int, answers: Mapping[str, int | None], now: datetime
) -> dict[str, int]:
    """Validate a compare-and-set autosave and return the merged option answers."""
    status = exam_status(exam, now)
    if status == "submitted":
        raise ExamClosed("exam already submitted")
    if status == "expired":
        raise ExamExpired("exam time has expired")
    if revision != exam.revision:
        raise StaleRevision("revision does not match the saved exam")
    allowed = {str(qid) for qid in exam.question_ids} - exam.free_text_ids
    merged = dict(exam.answers)
    for question_id, option in answers.items():
        if question_id not in allowed:
            raise InvalidAnswer("option answer for a question outside this exam's SBA items")
        if option is None:
            merged.pop(question_id, None)
        elif not 0 <= option <= 4:
            raise InvalidAnswer("selected option is out of range")
        else:
            merged[question_id] = option
    return merged


def merge_text(exam: ExamState, text_answers: Mapping[str, str | None]) -> dict[str, str]:
    """Merge free-text autosaves; call after ``autosave`` has checked status and revision.

    Only the exam's free-text items accept text; blank text clears the answer.
    """
    merged = dict(exam.text_answers)
    for question_id, answer in text_answers.items():
        if question_id not in exam.free_text_ids:
            raise InvalidAnswer("text answer for a question outside this exam's written items")
        if answer is None or not answer.strip():
            merged.pop(question_id, None)
        elif len(answer) > MAX_TEXT_CHARS:
            raise InvalidAnswer("text answer is too long")
        else:
            merged[question_id] = answer
    return merged
