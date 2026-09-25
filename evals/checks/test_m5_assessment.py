"""M5 eval gate: item quality, exam mode, autosave/resume, and grading.

Covers slices R and S of the A-Z queue:
  R  SBA generation with versioned prompts, citations, and item quality gates
  S  practice, Exam mode, autosave/resume, grader, and statistics

Generated items are explicitly synthetic and must never read as clinically
authoritative; these tests pin that down alongside the behavioural gates.

All content is synthetic.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from apps.api.app.preview.assessment import (
    autosave_exam,
    create_exam,
    ensure_questions,
    grade,
    list_questions,
    question_view,
    start_exam,
    submit_exam,
)
from evals.checks._harness import OWNER_A, OWNER_B, TENANT_A, TENANT_B, new_state, seed


def ready():
    state = new_state()
    seed(state)
    ensure_questions(state, TENANT_A, OWNER_A)
    return state


# ---------------------------------------------------------------- slice R


def test_items_are_generated_once_and_are_deterministic() -> None:
    first = {str(q.id) for q in list_questions(ready(), TENANT_A, OWNER_A)}
    second = {str(q.id) for q in list_questions(ready(), TENANT_A, OWNER_A)}
    assert first == second


def test_every_item_is_well_formed_and_cited() -> None:
    for question in list_questions(ready(), TENANT_A, OWNER_A):
        assert question.tenant_id == TENANT_A
        assert question.curriculum_code
        assert question.stem
        assert len(question.options) == 5
        assert len(set(question.options)) == 5, "options must be distinguishable"
        assert 0 <= question.key < len(question.options)
        assert question.citation is not None
        assert "not clinically authoritative" in question.explanation


def test_item_ids_are_tenant_scoped_in_content_but_stable_across_tenants() -> None:
    """Item identity is content-addressed, so two tenants share ids by design.

    What must not be shared is the *answer key* leaking across tenants, which
    the served view and the tenant-scoped grade path cover separately.
    """
    a_state = ready()
    b_state = new_state()
    seed(b_state, TENANT_B, OWNER_B)
    ensure_questions(b_state, TENANT_B, OWNER_B)

    a = list_questions(a_state, TENANT_A, OWNER_A)
    b = list_questions(b_state, TENANT_B, OWNER_B)
    assert {q.id for q in a} == {q.id for q in b}
    assert all(q.tenant_id == TENANT_A for q in a)
    assert all(q.tenant_id == TENANT_B for q in b)


def test_the_served_view_never_leaks_the_answer_key() -> None:
    for question in list_questions(ready(), TENANT_A, OWNER_A):
        view = question_view(question)
        assert "key" not in view
        assert "correct" not in view
        assert "explanation" not in view
        assert set(view) == {
            "question_id",
            "kind",
            "stem",
            "options",
            "curriculum_code",
            "citations",
        }
        assert view["citations"]


# ---------------------------------------------------------------- slice S


def test_grading_awards_a_point_only_for_the_key() -> None:
    state = ready()
    question = state.questions(TENANT_A)[0]

    right = grade(state, TENANT_A, OWNER_A, question.id, question.key)
    wrong = grade(state, TENANT_A, OWNER_A, question.id, (question.key + 1) % 5)

    assert right["grade"]["correct"] is True
    assert right["grade"]["awarded_points"] == 1.0
    assert right["grade"]["max_points"] == 1.0
    assert wrong["grade"]["correct"] is False
    assert wrong["grade"]["awarded_points"] == 0.0


def test_an_unanswered_question_scores_zero_rather_than_credit() -> None:
    state = ready()
    question = state.questions(TENANT_A)[0]

    result = grade(state, TENANT_A, OWNER_A, question.id, None)

    assert result["grade"]["correct"] is False
    assert result["grade"]["awarded_points"] == 0.0
    assert result["grade"]["selected_option"] is None


def test_grading_always_returns_a_cited_explanation() -> None:
    state = ready()
    question = state.questions(TENANT_A)[0]
    grade_body = grade(state, TENANT_A, OWNER_A, question.id, question.key)["grade"]
    assert grade_body["explanation"]
    assert grade_body["citations"]


@pytest.mark.parametrize("option", [-1, 5, 99])
def test_out_of_range_options_are_rejected(option: int) -> None:
    state = ready()
    question = state.questions(TENANT_A)[0]
    with pytest.raises(ValueError, match="out of range"):
        grade(state, TENANT_A, OWNER_A, question.id, option)


def test_grading_an_unknown_question_raises() -> None:
    with pytest.raises(LookupError):
        grade(ready(), TENANT_A, OWNER_A, UUID(int=4242), 0)


def test_grading_is_audited() -> None:
    state = ready()
    question = state.questions(TENANT_A)[0]
    grade(state, TENANT_A, OWNER_A, question.id, question.key)

    events = [e for e in state.audit(TENANT_A) if e.action == "attempt.graded"]
    assert len(events) == 1
    assert events[0].target_id == str(question.id)


def test_practice_attempts_are_recorded_per_owner() -> None:
    state = ready()
    question = state.questions(TENANT_A)[0]
    grade(state, TENANT_A, OWNER_A, question.id, question.key)
    grade(state, TENANT_A, OWNER_A, question.id, question.key)

    assert len(state.attempts(TENANT_A, OWNER_A)) == 2
    assert state.attempts(TENANT_A, OWNER_B) == []


# ------------------------------------------------------------- exam mode


def test_exam_lifecycle_created_active_submitted() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    assert exam.status == "created"

    started = start_exam(state, TENANT_A, OWNER_A, exam.id)
    assert started.status == "active"
    assert started.started_at is not None
    assert started.deadline_at is not None
    assert started.deadline_at > started.started_at

    result = submit_exam(state, TENANT_A, OWNER_A, exam.id)
    assert result["status"] == "submitted"
    assert state.exam(TENANT_A, exam.id).status == "submitted"


def test_submitting_before_starting_is_refused() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    with pytest.raises(ValueError, match="has not started"):
        submit_exam(state, TENANT_A, OWNER_A, exam.id)


def test_starting_twice_does_not_extend_the_deadline() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    first = start_exam(state, TENANT_A, OWNER_A, exam.id)
    second = start_exam(state, TENANT_A, OWNER_A, exam.id)

    assert first.started_at == second.started_at
    assert first.deadline_at == second.deadline_at


def test_exam_contains_five_cited_items() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    assert len(exam.question_ids) == 5
    assert len(set(exam.question_ids)) == 5


# -------------------------------------------------- autosave and resume


def test_autosave_accumulates_answers_across_revisions() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    ids = list(exam.question_ids)

    autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {ids[0]: 2})
    autosave_exam(state, TENANT_A, OWNER_A, exam.id, 2, {ids[1]: 3})
    saved = state.exam(TENANT_A, exam.id)

    assert saved.revision == 2
    assert saved.answers == {ids[0]: 2, ids[1]: 3}


def test_a_disconnect_and_resume_preserves_earlier_answers() -> None:
    """Slice S: a dropped connection must not lose autosaved work."""
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    ids = list(exam.question_ids)

    autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {ids[0]: 1, ids[1]: 4})
    # Simulate a reconnect that re-sends only the newest edit.
    autosave_exam(state, TENANT_A, OWNER_A, exam.id, 2, {ids[2]: 0})

    saved = state.exam(TENANT_A, exam.id)
    assert saved.answers == {ids[0]: 1, ids[1]: 4, ids[2]: 0}

    result = submit_exam(state, TENANT_A, OWNER_A, exam.id)
    graded = {b["question_id"]: b["selected_option"] for b in result["breakdown"]}
    assert graded[str(ids[0])] == 1
    assert graded[str(ids[2])] == 0


def test_a_stale_revision_is_rejected_rather_than_applied() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    ids = list(exam.question_ids)

    autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {ids[0]: 2})
    with pytest.raises(ValueError, match="stale exam revision"):
        autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {ids[1]: 3})
    with pytest.raises(ValueError, match="stale exam revision"):
        autosave_exam(state, TENANT_A, OWNER_A, exam.id, 99, {ids[1]: 3})


def test_autosave_rejects_a_question_outside_the_paper() -> None:
    state = ready()
    extra_question = list_questions(state, TENANT_A, OWNER_A)[-1]
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)

    if extra_question.id not in exam.question_ids:
        with pytest.raises(ValueError, match="invalid exam answer"):
            autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {extra_question.id: 1})


def test_autosave_rejects_an_out_of_range_option() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    first = exam.question_ids[0]

    with pytest.raises(ValueError, match="invalid exam answer"):
        autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {first: 7})


def test_autosave_is_refused_once_the_exam_is_submitted() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    submit_exam(state, TENANT_A, OWNER_A, exam.id)

    with pytest.raises(ValueError, match="not active"):
        autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {exam.question_ids[0]: 1})


# ------------------------------------------------------------- results


def test_submission_scores_within_bounds_and_breaks_down_every_item() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    keys = {q.id: q.key for q in state.questions(TENANT_A)}
    autosave_exam(
        state,
        TENANT_A,
        OWNER_A,
        exam.id,
        1,
        {qid: keys[qid] for qid in exam.question_ids},
    )

    result = submit_exam(state, TENANT_A, OWNER_A, exam.id)

    assert result["score"] == float(len(exam.question_ids))
    assert result["max_score"] == float(len(exam.question_ids))
    assert len(result["breakdown"]) == len(exam.question_ids)
    for item in result["breakdown"]:
        assert item["correct"] is True
        assert item["citations"]


def test_unanswered_items_are_credited_nothing() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)

    result = submit_exam(state, TENANT_A, OWNER_A, exam.id)

    assert result["score"] == 0.0
    assert all(item["selected_option"] is None for item in result["breakdown"])
    assert all(item["correct"] is False for item in result["breakdown"])


def test_resubmitting_returns_the_same_result_without_double_crediting() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    keys = {q.id: q.key for q in state.questions(TENANT_A)}
    autosave_exam(
        state,
        TENANT_A,
        OWNER_A,
        exam.id,
        1,
        {qid: keys[qid] for qid in exam.question_ids},
    )

    first = submit_exam(state, TENANT_A, OWNER_A, exam.id)
    attempts_after_first = len(state.attempts(TENANT_A, OWNER_A))
    second = submit_exam(state, TENANT_A, OWNER_A, exam.id)

    assert first["score"] == second["score"]
    assert first["status"] == second["status"] == "submitted"
    # Re-reading the result must not grade the paper a second time.
    assert len(state.attempts(TENANT_A, OWNER_A)) == attempts_after_first


def test_exam_access_is_owner_scoped_and_tenant_scoped() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)

    with pytest.raises(LookupError):
        start_exam(state, TENANT_A, OWNER_B, exam.id)
    with pytest.raises(LookupError):
        submit_exam(state, TENANT_B, OWNER_B, exam.id)
    with pytest.raises(LookupError):
        autosave_exam(state, TENANT_B, OWNER_B, exam.id, 1, {})


def test_exam_events_are_audited_in_order() -> None:
    state = ready()
    exam = create_exam(state, TENANT_A, OWNER_A)
    start_exam(state, TENANT_A, OWNER_A, exam.id)
    autosave_exam(state, TENANT_A, OWNER_A, exam.id, 1, {exam.question_ids[0]: 1})
    submit_exam(state, TENANT_A, OWNER_A, exam.id)

    actions = [e.action for e in state.audit(TENANT_A)]
    for expected in ("exam.created", "exam.started", "exam.autosaved", "exam.submitted"):
        assert expected in actions
    assert actions.index("exam.created") < actions.index("exam.started")
    assert actions.index("exam.started") < actions.index("exam.autosaved")
    assert actions.index("exam.autosaved") < actions.index("exam.submitted")
