"""M5 eval gate: item quality, key hiding, practice grading, and timed exam mode.

Covers slices R and S of the A-Z queue against the DURABLE assessment code
(``apps/api/app/assessment``, ``apps/api/app/api/assessment.py`` and
``exams.py``, ``packages/assessment``), driven over HTTP with an in-memory
table set that answers the service's SQL and a fixed clock (see
``evals/checks/_m5_support.py``):

  R  stored items are well formed, cited to supplied excerpts, and active only
     when the independent checker passed them; the served view never carries a
     key, explanation, or citation before the item is answered.
  S  practice grading awards the point only for the key, reveals a cited
     explanation, and refuses out-of-range or missing answers; the exam
     lifecycle (create, autosave, submit) keeps a server-fixed deadline,
     compare-and-set revisions, resume-safe answers, idempotent submission, and
     owner/tenant-scoped access.

Tenant isolation here is one table set per tenant; the database RLS proofs for
questions, exams, and attempts run in ``evals/checks/test_assessment_live.py``
and ``test_assessment_depth_live.py``.

All content is synthetic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from apps.api.app.assessment import generation
from apps.api.tests.test_assessment_validation import EXCERPTS, SUPPLIED, sba_item
from evals.checks._m5_support import (
    NOW,
    OWNER_A,
    OWNER_B,
    PASS,
    PUBLIC_FIELDS,
    TENANT_A,
    TENANT_B,
    Clock,
    Harness,
)
from packages.assessment.grading import InvalidAnswer, grade_sba
from packages.assessment.validation import check_item


@pytest.fixture
def h(monkeypatch: pytest.MonkeyPatch) -> Harness:
    harness = Harness(monkeypatch)
    harness.seed()
    return harness


def _ids(exam: dict[str, Any]) -> list[str]:
    return [q["id"] for q in exam["questions"]]


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------- slice R


def test_every_item_is_well_formed_and_cited(h: Harness) -> None:
    refs = {excerpt.ref for excerpt in EXCERPTS}
    for question in h.db.owned(OWNER_A):
        texts = [option["text"] for option in question["options"]]
        assert question["type"] == "sba" and question["stem"] and question["topic"]
        assert len(texts) == 5 and len(set(texts)) == 5, "options must be distinguishable"
        assert 0 <= question["answer"]["key"] < 5
        assert question["citations"] and {c["ref"] for c in question["citations"]} <= refs
        assert all(option["citations"] for option in question["options"])
        assert question["status"] == "active" and question["quality"]["passed"] is True
        assert question["agent_version"] == "question_generate/v1+question_check/v1"
    assert len({q["answer"]["key"] for q in h.db.owned(OWNER_A)}) == 5  # keys vary


def test_only_checked_and_cited_items_become_active() -> None:
    assert check_item(sba_item(), "sba", SUPPLIED) == []
    assert "citation_not_supplied" in check_item(sba_item(citations=["E9"]), "sba", SUPPLIED)
    assert "sba_key_out_of_range" in check_item(sba_item(key_index=-1), "sba", SUPPLIED)
    unchecked = generation.to_row(sba_item(), None, EXCERPTS, "fcps2_theory")
    assert unchecked["status"] == "draft" and unchecked["quality"]["passed"] is False
    failed = PASS.model_copy(update={"verdict": "fail", "no_cueing": False})
    assert generation.to_row(sba_item(), failed, EXCERPTS, "frcr")["status"] == "draft"
    assert generation.to_row(sba_item(), PASS, EXCERPTS, "frcr")["status"] == "active"


def test_the_served_view_never_leaks_the_answer_key(h: Harness) -> None:
    listed = h.client.get("/v1/questions").json()
    assert len(listed) == 8
    for view in listed:
        assert set(view) == PUBLIC_FIELDS
        assert all(isinstance(option, str) for option in view["options"])
        assert "because" not in str(view) and "Crazy paving" not in str(view)
    exam = h.create_exam()
    assert exam["result"] is None and exam["answers"] == {}
    assert all(set(q) == PUBLIC_FIELDS for q in exam["questions"])
    # While the exam is open the practice route will not act as a key oracle.
    blocked = h.attempt(_ids(exam)[0], 0)
    assert blocked.status_code == 409 and "key" not in blocked.json()
    assert h.db.attempts == []


def test_the_question_bank_is_owner_and_tenant_scoped(h: Harness) -> None:
    """Replaces the preview's content-addressed ids: durable items are per owner."""
    question = h.db.owned(OWNER_A)[0]
    for user, tenant in ((OWNER_B, TENANT_A), (OWNER_B, TENANT_B), (OWNER_A, TENANT_B)):
        h.act_as(user, tenant)
        assert h.client.get("/v1/questions").json() == []
        assert h.attempt(question["id"], 0).status_code == 404
    assert h.db.attempts == []


# ---------------------------------------------------------------- slice S


def test_grading_awards_a_point_only_for_the_key(h: Harness) -> None:
    question = h.db.owned(OWNER_A)[1]
    key = question["answer"]["key"]
    right = h.attempt(question["id"], key).json()
    wrong = h.attempt(question["id"], (key + 1) % 5).json()
    assert (right["correct"], right["score"], right["max_score"]) == (True, 1.0, 1.0)
    assert (wrong["correct"], wrong["score"], wrong["max_score"]) == (False, 0.0, 1.0)
    assert right["key"] == wrong["key"] == key
    assert [a["score"] for a in h.db.attempts] == [1.0, 0.0]
    assert [call[5] for call in h.weakness] == [True, False]  # the miss feeds the loop


def test_an_unanswered_question_scores_zero_rather_than_credit(h: Harness) -> None:
    question = h.db.owned(OWNER_A)[0]
    assert h.attempt(question["id"], None).status_code == 422
    assert h.db.attempts == []
    graded = grade_sba(question, None)
    assert (graded["correct"], graded["score"], graded["selected_option"]) == (False, 0.0, None)


def test_grading_always_returns_a_cited_explanation(h: Harness) -> None:
    question = h.db.owned(OWNER_A)[2]
    body = h.attempt(question["id"], question["answer"]["key"]).json()
    assert body["explanation"] and body["citations"]
    assert len(body["option_explanations"]) == 5
    assert all(o["explanation"] and o["citations"] for o in body["option_explanations"])


@pytest.mark.parametrize("option", [-1, 5, 99])
def test_out_of_range_options_are_rejected(h: Harness, option: int) -> None:
    question = h.db.owned(OWNER_A)[0]
    assert h.attempt(question["id"], option).status_code == 422
    assert h.db.attempts == []
    with pytest.raises(InvalidAnswer):
        grade_sba(question, option)


def test_grading_an_unknown_question_is_not_found(h: Harness) -> None:
    assert h.attempt(uuid4(), 0).status_code == 404


def test_practice_attempts_are_recorded_per_owner(h: Harness) -> None:
    question = h.db.owned(OWNER_A)[0]
    h.attempt(question["id"], question["answer"]["key"])
    h.attempt(question["id"], question["answer"]["key"])
    h.seed(3, owner=OWNER_B)
    h.act_as(OWNER_B, TENANT_A)
    theirs = h.db.owned(OWNER_B)[0]
    h.attempt(theirs["id"], 0)
    assert len(h.db.attempts_of(OWNER_A)) == 2 and len(h.db.attempts_of(OWNER_B)) == 1
    assert {a["question_id"] for a in h.db.attempts_of(OWNER_B)} == {theirs["id"]}


# ------------------------------------------------------------- exam mode


def test_exam_lifecycle_create_autosave_submit(h: Harness) -> None:
    exam = h.create_exam(count=5, minutes=30)
    assert exam["status"] == "active" and exam["revision"] == 0
    assert _time(exam["deadline_at"]) - _time(exam["started_at"]) == timedelta(minutes=30)
    assert len(_ids(exam)) == 5 and len(set(_ids(exam))) == 5
    assert h.autosave(exam["id"], 0, {_ids(exam)[0]: 1}).status_code == 200
    submitted = h.submit(exam["id"]).json()
    assert submitted["status"] == "submitted" and submitted["result"]["question_count"] == 5
    assert h.client.get(f"/v1/exams/{exam['id']}").json()["status"] == "submitted"
    listed = h.client.get("/v1/exams").json()
    assert [(e["id"], e["status"], e["answered"]) for e in listed] == [
        (exam["id"], "submitted", 1)]


def test_the_deadline_is_fixed_by_the_server_and_never_extended(h: Harness) -> None:
    """Replaces "starting twice": durable exams start on creation with a fixed deadline."""
    exam = h.create_exam(minutes=20)
    Clock.now = NOW + timedelta(minutes=5)
    saved = h.autosave(exam["id"], 0, {_ids(exam)[0]: 2}).json()
    reread = h.client.get(f"/v1/exams/{exam['id']}").json()
    assert saved["deadline_at"] == reread["deadline_at"] == exam["deadline_at"]
    assert reread["started_at"] == exam["started_at"]


def test_an_expired_exam_refuses_autosave_and_is_graded_from_saved_answers(h: Harness) -> None:
    """Replaces "submit before start": the server clock, not the client, closes the paper."""
    exam = h.create_exam(minutes=10)
    first = _ids(exam)[0]
    h.autosave(exam["id"], 0, {first: h.key_of(first)})
    Clock.now = NOW + timedelta(minutes=10)
    late = h.autosave(exam["id"], 1, {_ids(exam)[1]: 0})
    assert (late.status_code, late.json()["detail"]) == (409, "exam_time_expired")
    finalised = h.client.get(f"/v1/exams/{exam['id']}").json()
    assert finalised["status"] == "submitted" and finalised["result"]["timed_out"] is True
    assert finalised["result"]["score"] == 1.0 and finalised["result"]["answered"] == 1


def test_autosave_accumulates_answers_across_revisions(h: Harness) -> None:
    exam = h.create_exam()
    ids = _ids(exam)
    assert h.autosave(exam["id"], 0, {ids[0]: 2}).json()["revision"] == 1
    saved = h.autosave(exam["id"], 1, {ids[1]: 3}).json()
    assert saved["revision"] == 2 and saved["answers"] == {ids[0]: 2, ids[1]: 3}
    cleared = h.autosave(exam["id"], 2, {ids[0]: None}).json()
    assert cleared["answers"] == {ids[1]: 3}


def test_a_disconnect_and_resume_preserves_earlier_answers(h: Harness) -> None:
    exam = h.create_exam()
    ids = _ids(exam)
    h.autosave(exam["id"], 0, {ids[0]: 1, ids[1]: 4})
    resumed = h.client.get(f"/v1/exams/{exam['id']}").json()  # a new device reconnects
    assert resumed["answers"] == {ids[0]: 1, ids[1]: 4} and resumed["revision"] == 1
    h.autosave(exam["id"], resumed["revision"], {ids[2]: 0})  # only the newest edit
    result = h.submit(exam["id"]).json()["result"]
    graded = {item["question_id"]: item["selected_option"] for item in result["items"]}
    assert (graded[ids[0]], graded[ids[1]], graded[ids[2]]) == (1, 4, 0)


def test_a_stale_revision_is_rejected_rather_than_applied(h: Harness) -> None:
    exam = h.create_exam()
    ids = _ids(exam)
    h.autosave(exam["id"], 0, {ids[0]: 2})
    for revision in (0, 99):
        stale = h.autosave(exam["id"], revision, {ids[1]: 3})
        assert (stale.status_code, stale.json()["detail"]) == (409, "stale_revision")
    assert h.client.get(f"/v1/exams/{exam['id']}").json()["answers"] == {ids[0]: 2}


def test_autosave_rejects_a_question_outside_the_paper(h: Harness) -> None:
    exam = h.create_exam(count=5)
    outside = next(str(q["id"]) for q in h.db.owned(OWNER_A) if str(q["id"]) not in _ids(exam))
    for foreign in (outside, str(uuid4())):
        refused = h.autosave(exam["id"], 0, {foreign: 1})
        assert (refused.status_code, refused.json()["detail"]) == (422, "invalid_answer")


@pytest.mark.parametrize("option", [7, 5, -1])
def test_autosave_rejects_an_out_of_range_option(h: Harness, option: int) -> None:
    exam = h.create_exam()
    refused = h.autosave(exam["id"], 0, {_ids(exam)[0]: option})
    assert (refused.status_code, refused.json()["detail"]) == (422, "invalid_answer")


def test_autosave_is_refused_once_the_exam_is_submitted(h: Harness) -> None:
    exam = h.create_exam()
    h.submit(exam["id"])
    refused = h.autosave(exam["id"], 0, {_ids(exam)[0]: 1})
    assert (refused.status_code, refused.json()["detail"]) == (409, "exam_submitted")


def test_submission_scores_within_bounds_and_breaks_down_every_item(h: Harness) -> None:
    exam = h.create_exam(count=5)
    h.autosave(exam["id"], 0, {qid: h.key_of(qid) for qid in _ids(exam)})
    result = h.submit(exam["id"]).json()["result"]
    assert (result["score"], result["max_score"], result["percent"]) == (5.0, 5.0, 100.0)
    assert [item["question_id"] for item in result["items"]] == _ids(exam)
    for item in result["items"]:
        assert item["correct"] is True and item["citations"]
        assert item["key"] == item["selected_option"] and item["explanation"]
    assert len(h.db.attempts_of(OWNER_A)) == 5


def test_unanswered_items_are_credited_nothing(h: Harness) -> None:
    exam = h.create_exam(count=5)
    result = h.submit(exam["id"]).json()["result"]
    assert (result["score"], result["max_score"], result["answered"]) == (0.0, 5.0, 0)
    assert all(item["selected_option"] is None for item in result["items"])
    assert all(item["correct"] is False for item in result["items"])


def test_resubmitting_returns_the_same_result_without_double_crediting(h: Harness) -> None:
    exam = h.create_exam(count=5)
    ids = _ids(exam)
    h.autosave(exam["id"], 0, {ids[0]: h.key_of(ids[0]), ids[1]: (h.key_of(ids[1]) + 1) % 5})
    first = h.submit(exam["id"]).json()
    attempts, weakness = len(h.db.attempts), len(h.weakness)
    second = h.submit(exam["id"]).json()
    assert second["result"] == first["result"] and second["status"] == "submitted"
    assert second["submitted_at"] == first["submitted_at"]
    assert len(h.db.attempts) == attempts == 5 and len(h.weakness) == weakness


def test_exam_access_is_owner_scoped_and_tenant_scoped(h: Harness) -> None:
    exam = h.create_exam()
    url = f"/v1/exams/{exam['id']}"
    for user, tenant in ((OWNER_B, TENANT_A), (OWNER_B, TENANT_B), (OWNER_A, TENANT_B)):
        h.act_as(user, tenant)
        assert h.client.get(url).status_code == 404
        assert h.autosave(exam["id"], 0, {}).status_code == 404
        assert h.submit(exam["id"]).status_code == 404
        assert h.client.get("/v1/exams").json() == []
    h.act_as(OWNER_A, TENANT_A)
    reread = h.client.get(url).json()
    assert reread["status"] == "active" and reread["revision"] == 0
