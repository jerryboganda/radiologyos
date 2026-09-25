from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from apps.api.app.preview.knowledge import ensure_knowledge
from apps.api.app.preview.state import (
    PreviewAttempt,
    PreviewAudit,
    PreviewExam,
    PreviewQuestion,
    PreviewState,
)

_CODES = ("CHEST", "NEURO", "CARDIAC", "ABDOMEN", "MSK")


def _question_id(index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"radbrain:preview:question:{index}")


def ensure_questions(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> None:
    if state.questions(tenant_id):
        return
    ensure_knowledge(state, tenant_id, owner_id)
    citation = {
        "source_id": "synthetic",
        "page_no": 1,
        "block_id": "synthetic-claim-1",
        "bbox": [0.0, 0.0, 0.0, 0.0],
    }
    for index, code in enumerate(_CODES, start=1):
        state.add_question(
            PreviewQuestion(
                id=_question_id(index),
                tenant_id=tenant_id,
                curriculum_code=code,
                stem=f"Synthetic preview question for {code}?",
                options=("Option A", "Option B", "Option C", "Option D", "Option E"),
                key=index % 5,
                explanation="Synthetic explanation; not clinically authoritative.",
                citation=citation,
            )
        )


def list_questions(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> list[PreviewQuestion]:
    ensure_questions(state, tenant_id, owner_id)
    return state.questions(tenant_id)


def question_view(question: PreviewQuestion) -> dict[str, Any]:
    return {
        "question_id": str(question.id),
        "kind": "sba",
        "stem": question.stem,
        "options": question.options,
        "curriculum_code": question.curriculum_code,
        "citations": (question.citation,),
    }


def grade(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    question_id: UUID,
    selected_option: int | None,
) -> dict[str, Any]:
    question = next((item for item in state.questions(tenant_id) if item.id == question_id), None)
    if question is None:
        raise LookupError("question not found")
    if selected_option is not None and selected_option not in range(5):
        raise ValueError("selected option is out of range")
    correct = selected_option is not None and selected_option == question.key
    attempt = PreviewAttempt(
        id=state.new_id(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        question_id=question_id,
        selected_option=selected_option,
        correct=correct,
        created_at=state.now(),
    )
    state.add_attempt(attempt)
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="attempt.graded",
            target_type="question",
            target_id=str(question_id),
            created_at=state.now(),
        )
    )
    return {
        "attempt_id": str(attempt.id),
        "grade": {
            "question_id": str(question_id),
            "selected_option": selected_option,
            "correct": correct,
            "awarded_points": 1.0 if correct else 0.0,
            "max_points": 1.0,
            "explanation": question.explanation,
            "citations": (question.citation,),
        },
    }


def create_exam(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> PreviewExam:
    questions = list_questions(state, tenant_id, owner_id)[:5]
    exam = PreviewExam(
        id=state.new_id(),
        tenant_id=tenant_id,
        owner_id=owner_id,
        question_ids=tuple(question.id for question in questions),
    )
    state.add_exam(exam)
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="exam.created",
            target_type="exam",
            target_id=str(exam.id),
            created_at=state.now(),
        )
    )
    return exam


def start_exam(state: PreviewState, tenant_id: UUID, owner_id: UUID, exam_id: UUID) -> PreviewExam:
    exam = state.exam(tenant_id, exam_id)
    if exam is None or exam.owner_id != owner_id:
        raise LookupError("exam not found")
    if exam.status == "created":
        exam.status = "active"
        exam.started_at = state.now()
        exam.deadline_at = state.now() + timedelta(seconds=600)
        state.add_audit(
            PreviewAudit(
                tenant_id=tenant_id,
                actor_id=owner_id,
                action="exam.started",
                target_type="exam",
                target_id=str(exam.id),
                created_at=state.now(),
            )
        )
    return exam


def autosave_exam(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    exam_id: UUID,
    revision: int,
    answers: dict[UUID, int],
) -> PreviewExam:
    exam = state.exam(tenant_id, exam_id)
    if exam is None or exam.owner_id != owner_id:
        raise LookupError("exam not found")
    if exam.status != "active":
        raise ValueError("exam is not active")
    if revision != exam.revision + 1:
        raise ValueError("stale exam revision")
    valid_ids = set(exam.question_ids)
    if any(
        question_id not in valid_ids or option not in range(5)
        for question_id, option in answers.items()
    ):
        raise ValueError("invalid exam answer")
    exam.answers.update(answers)
    exam.revision = revision
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="exam.autosaved",
            target_type="exam",
            target_id=str(exam.id),
            created_at=state.now(),
        )
    )
    return exam


def submit_exam(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    exam_id: UUID,
) -> dict[str, Any]:
    exam = state.exam(tenant_id, exam_id)
    if exam is None or exam.owner_id != owner_id:
        raise LookupError("exam not found")
    if exam.status in {"submitted", "timed_out"}:
        return _exam_result(state, exam)
    if exam.status == "created":
        raise ValueError("exam has not started")
    timed_out = exam.deadline_at is not None and state.now() > exam.deadline_at
    breakdown: list[dict[str, Any]] = []
    for question_id in exam.question_ids:
        selected = exam.answers.get(question_id)
        result = grade(state, tenant_id, owner_id, question_id, selected)
        grade_item = cast(dict[str, Any], result["grade"])
        if selected is None:
            grade_item["correct"] = False
            grade_item["awarded_points"] = 0.0
        breakdown.append(grade_item)
    exam.status = "timed_out" if timed_out else "submitted"
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="exam.submitted",
            target_type="exam",
            target_id=str(exam.id),
            created_at=state.now(),
        )
    )
    return _exam_result(state, exam, breakdown)


def _exam_result(
    state: PreviewState,
    exam: PreviewExam,
    breakdown: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if breakdown is None:
        breakdown = []
        for question_id in exam.question_ids:
            question = next(
                item for item in state.questions(exam.tenant_id) if item.id == question_id
            )
            selected = exam.answers.get(question_id)
            breakdown.append(
                {
                    "question_id": str(question_id),
                    "selected_option": selected,
                    "correct": selected == question.key,
                    "awarded_points": 1.0 if selected == question.key else 0.0,
                    "max_points": 1.0,
                    "explanation": question.explanation,
                    "citations": (question.citation,),
                }
            )
    score = sum(float(item["awarded_points"]) for item in breakdown)
    return {
        "exam_id": str(exam.id),
        "status": exam.status,
        "score": score,
        "max_score": float(len(exam.question_ids)),
        "breakdown": tuple(breakdown),
        "submitted_at": state.now(),
    }
