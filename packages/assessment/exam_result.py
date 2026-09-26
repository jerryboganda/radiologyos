"""Exam results for mixed SBA and free-text papers (no database, no model calls).

On submission SBA items are graded at once by exact match. A free-text item
(SEQ, image case, viva) with a blank answer is graded zero at once against its
frozen scheme; any other free-text item is stored ``pending`` and graded later
by the worker, which fills the graded item in with ``fill_item``. Every item
carries ``status`` (``graded``, ``pending``, or ``failed``); the summary counts
pending items as zero until they are graded and says so in ``grading``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from packages.assessment.grading import ExamState, apply_seq_grade, grade_sba
from packages.assessment.models import SeqGrade

FREE_TEXT_TYPES = frozenset({"seq", "image_case", "viva"})
NO_ANSWER_FEEDBACK = "No answer was submitted for this item."


def is_free_text(question: Mapping[str, Any]) -> bool:
    return question.get("type") in FREE_TEXT_TYPES


def scheme_max(question: Mapping[str, Any]) -> float:
    scheme = question["answer"].get("marking_scheme", [])
    return round(sum(float(point["marks"]) for point in scheme), 2)


def free_text_base(question: Mapping[str, Any], answer_text: str) -> dict[str, Any]:
    answer = question["answer"]
    return {
        "question_id": str(question["id"]),
        "type": question["type"],
        "topic": question.get("topic", ""),
        "answer_text": answer_text,
        "max_score": scheme_max(question),
        "model_answer": answer.get("model_answer", ""),
        "key_findings": answer.get("key_findings", []),
        "explanation": question.get("explanation", ""),
        "citations": question["citations"],
    }


def graded_free_text(base: Mapping[str, Any], graded: Mapping[str, Any]) -> dict[str, Any]:
    return {**base, "status": "graded", "score": graded["score"],
            "max_score": graded["max_score"], "points": graded["points"],
            "feedback": graded["feedback"]}


def free_text_item(question: Mapping[str, Any], answer_text: str) -> dict[str, Any]:
    base = free_text_base(question, answer_text)
    if not answer_text.strip():
        blank = apply_seq_grade(question["answer"].get("marking_scheme", []),
                                SeqGrade(points=[], feedback=NO_ANSWER_FEEDBACK))
        return graded_free_text(base, blank)
    return {**base, "status": "pending", "score": None, "points": [], "feedback": ""}


def failed_item(item: Mapping[str, Any], error_code: str) -> dict[str, Any]:
    return {**item, "status": "failed", "score": None, "error": error_code}


def _answered(item: Mapping[str, Any]) -> bool:
    if item.get("type", "sba") == "sba":
        return item.get("selected_option") is not None
    return bool(str(item.get("answer_text") or "").strip())


def _by_topic(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    topics: dict[str, dict[str, float]] = {}
    for item in items:
        t = topics.setdefault(item.get("topic") or "untagged", {
            "correct": 0, "total": 0, "answered": 0, "score": 0.0, "max_score": 0.0})
        t["total"] += 1
        t["correct"] += 1 if item.get("correct") else 0
        t["answered"] += 1 if _answered(item) else 0
        t["score"] += float(item.get("score") or 0.0)
        t["max_score"] += float(item["max_score"])
    return [
        {"topic": name, "correct": int(c["correct"]), "total": int(c["total"]),
         "answered": int(c["answered"]), "score": round(c["score"], 2),
         "max_score": round(c["max_score"], 2)}
        for name, c in sorted(topics.items())
    ]


def summarize(items: Sequence[Mapping[str, Any]], question_count: int) -> dict[str, Any]:
    """Totals over graded items; missing (deleted) questions count one mark each."""
    missing = max(0, question_count - len(items))
    score = round(sum(float(item.get("score") or 0.0) for item in items), 2)
    max_score = round(sum(float(item["max_score"]) for item in items) + missing, 2)
    pending = sum(1 for item in items if item.get("status") == "pending")
    return {
        "score": score,
        "max_score": max_score,
        "percent": round(100.0 * score / max_score, 1) if max_score else 0.0,
        "answered": sum(1 for item in items if _answered(item)),
        "pending": pending,
        "failed": sum(1 for item in items if item.get("status") == "failed"),
        "grading": "pending" if pending else "complete",
        "question_count": question_count,
        "by_topic": _by_topic(items),
    }


def grade_exam(exam: ExamState, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Grade SBA items now; free-text items are graded now if blank, else pending."""
    items: list[dict[str, Any]] = []
    for question_id in (str(q) for q in exam.question_ids):
        question = questions.get(question_id)
        if question is None:  # deleted after the exam started: counts as unanswered
            continue
        if is_free_text(question):
            items.append(free_text_item(question, exam.text_answers.get(question_id, "")))
        else:
            graded = grade_sba(question, exam.answers.get(question_id))
            items.append({**graded, "type": "sba", "status": "graded"})
    return {**summarize(items, len(exam.question_ids)), "items": items}


def fill_item(result: Mapping[str, Any], question_id: str,
              item: Mapping[str, Any]) -> dict[str, Any]:
    """Replace one item in a stored result and recompute the summary."""
    items = [dict(item) if existing["question_id"] == question_id else existing
             for existing in result["items"]]
    count = int(result.get("question_count") or len(items))
    return {**result, **summarize(items, count), "items": items}


def pending_ids(result: Mapping[str, Any] | None) -> list[str]:
    if not result:
        return []
    return [item["question_id"] for item in result.get("items", [])
            if item.get("status") == "pending"]
