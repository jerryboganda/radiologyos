from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from apps.api.app.preview.assessment import list_questions, question_view
from apps.api.app.preview.learning import create_plan
from apps.api.app.preview.state import PreviewState

TENANT = UUID("20000000-0000-0000-0000-000000000002")
OWNER = UUID("10000000-0000-0000-0000-000000000001")


def _plan_shape(state: PreviewState) -> dict[str, object]:
    plan = create_plan(
        state,
        TENANT,
        OWNER,
        date.today() + timedelta(days=60),
        8,
        60,
    )
    return {
        "phase": plan["phase"],
        "days_remaining": plan["days_remaining"],
        "priority": plan["priority"],
        "notice": plan["notice"],
    }


def test_preview_planner_and_question_contract_are_deterministic() -> None:
    first = PreviewState()
    second = PreviewState()
    plan_first = _plan_shape(first)
    plan_second = _plan_shape(second)
    questions_first = [question_view(question) for question in list_questions(first, TENANT, OWNER)]
    questions_second = [
        question_view(question) for question in list_questions(second, TENANT, OWNER)
    ]

    assert plan_first == plan_second
    assert questions_first == questions_second
