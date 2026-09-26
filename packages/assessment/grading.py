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


def exam_status(exam: ExamState, now: datetime) -> str:
    if exam.submitted_at is not None:
        return "submitted"
    if exam.deadline_at is not None and now >= exam.deadline_at:
        return "expired"
    return "active"


def autosave(
    exam: ExamState, revision: int, answers: Mapping[str, int | None], now: datetime
) -> dict[str, int]:
    """Validate a compare-and-set autosave and return the merged answers."""
    status = exam_status(exam, now)
    if status == "submitted":
        raise ExamClosed("exam already submitted")
    if status == "expired":
        raise ExamExpired("exam time has expired")
    if revision != exam.revision:
        raise StaleRevision("revision does not match the saved exam")
    allowed = {str(qid) for qid in exam.question_ids}
    merged = dict(exam.answers)
    for question_id, option in answers.items():
        if question_id not in allowed:
            raise InvalidAnswer("answer for a question outside this exam")
        if option is None:
            merged.pop(question_id, None)
        elif not 0 <= option <= 4:
            raise InvalidAnswer("selected option is out of range")
        else:
            merged[question_id] = option
    return merged


def grade_exam(
    exam: ExamState, questions: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Grade every exam item deterministically; unanswered items score zero."""
    items = []
    by_topic: dict[str, dict[str, float]] = {}
    for question_id in (str(q) for q in exam.question_ids):
        question = questions.get(question_id)
        if question is None:  # deleted after the exam started: counts as unanswered
            continue
        item = grade_sba(question, exam.answers.get(question_id))
        items.append(item)
        topic = by_topic.setdefault(item["topic"] or "untagged",
                                    {"correct": 0, "total": 0, "answered": 0})
        topic["total"] += 1
        topic["correct"] += 1 if item["correct"] else 0
        topic["answered"] += 0 if item["selected_option"] is None else 1
    score = sum(item["score"] for item in items)
    total = len(exam.question_ids)
    return {
        "score": score,
        "max_score": float(total),
        "percent": round(100.0 * score / total, 1) if total else 0.0,
        "answered": sum(1 for item in items if item["selected_option"] is not None),
        "by_topic": [
            {"topic": name, **{k: int(v) for k, v in counts.items()}}
            for name, counts in sorted(by_topic.items())
        ],
        "items": items,
    }
