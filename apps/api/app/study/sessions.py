"""Today session use cases: build once per local day, resume, answer, complete.

``GET /v1/study/sessions/today`` builds the day's session from the day's plan the
first time it is asked for (idempotent per user and local day, also under a
race: the unique row keeps the first build) and returns the stored one after
that, so a reload or another device resumes exactly where the user stopped.
Completing a session freezes a summary (including weighted coverage, which
feeds the pace projection) and clears tomorrow's cached plan so the nightly
replan rebuilds it from the new mastery.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from apps.api.app.study import session_view
from apps.api.app.study.ports import SessionRepo
from apps.api.app.study.service import (
    Invalid,
    NotFound,
    StudyError,
    due_cards,
    ensure_plan,
    local_day,
    require_profile,
)
from apps.api.app.study.signals import curriculum_nodes, topic_rows
from packages.assessment.exam_result import pending_ids
from packages.assessment.grading import InvalidAnswer, grade_sba
from packages.study import heatmap
from packages.study.projection import Topic, weighted_coverage
from packages.study.session import (
    MAX_FIGURES,
    MAX_REVIEW_CARDS,
    SESSION_VERSION,
    Retest,
    SbaCandidate,
    SessionInputs,
    VivaChoice,
    build_steps,
    focus_codes,
    focus_topic,
    learn_chunk_limit,
    plan_block,
    self_review_prompt,
    summarize,
)

GRACE = timedelta(seconds=30)
FREE_TEXT = ("viva", "image_case", "seq")


class StepClosed(StudyError):
    status_code = 409


@dataclass(frozen=True, slots=True)
class Grading:
    """Free-text items to hand to the grading worker once the transaction commits."""

    exam_id: UUID
    question_ids: list[str]


def _days_since(at: datetime | None, now: datetime) -> float | None:
    return None if at is None else max((now - at).total_seconds() / 86400, 0.0)


def _nodes() -> list[heatmap.Node]:
    return [heatmap.Node(n.code, n.parent_code, n.level, n.title) for n in curriculum_nodes()]


def _viva_choice(plan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                 chunk_ids: Sequence[str], topic: Mapping[str, str] | None,
                 now: datetime) -> VivaChoice | None:
    if plan_block(plan, "viva") is None:
        return None
    parent_of = heatmap.parents(_nodes())
    today, _ = focus_codes(plan)

    def rank(row: Mapping[str, Any]) -> tuple[int, float]:
        near = any(heatmap.within(row["curriculum_code"], c, parent_of) for c in today)
        since = _days_since(row["last_attempt_at"], now)
        return (0 if near else 1, -(since if since is not None else 1e9))

    if rows:
        best = sorted(rows, key=rank)[0]
        return VivaChoice("graded", question_id=str(best["question_id"]))
    if chunk_ids and topic:
        return VivaChoice("self_review", reference_chunk_id=chunk_ids[0],
                          prompt=self_review_prompt(topic["title"]))
    return None


async def _inputs(repo: SessionRepo, user_id: UUID, plan: Mapping[str, Any],
                  now: datetime, day: date) -> SessionInputs:
    nodes = _nodes()
    parent_of = heatmap.parents(nodes)
    topic = focus_topic(plan)
    cards = await due_cards(repo, user_id, now, MAX_REVIEW_CARDS)
    chunk_ids: list[str] = []
    figure_ids: list[str] = []
    if topic and plan_block(plan, "learn"):
        chunk_ids, figure_ids = await repo.learn_material(
            user_id, heatmap.subtree(topic["code"], nodes), learn_chunk_limit(plan), MAX_FIGURES)
    sba = await repo.question_candidates(user_id, ["sba"])
    retests = await repo.open_retests(user_id, 50)
    open_text = await repo.question_candidates(user_id, FREE_TEXT)
    return SessionInputs(
        plan=plan, card_ids=[str(c["id"]) for c in cards], topic=topic,
        chunk_ids=chunk_ids, figure_ids=figure_ids,
        candidates=[SbaCandidate(str(r["question_id"]), r["curriculum_code"],
                                 _days_since(r["last_attempt_at"], now)) for r in sba],
        retests=[Retest(str(r["id"]), str(r["question_id"])) for r in retests],
        viva=_viva_choice(plan, open_text, chunk_ids, topic, now),
        within=lambda code, root: heatmap.within(code, root, parent_of),
        seed=(user_id.int ^ day.toordinal()) & 0xFFFFFFFF,
    )


async def today_session(repo: SessionRepo, user_id: UUID, now: datetime) -> dict[str, Any]:
    profile = await require_profile(repo, user_id)
    day = local_day(profile, now)
    row = await repo.get_session(user_id, day)
    if row is None:
        plan = await ensure_plan(repo, user_id, now)
        steps = build_steps(await _inputs(repo, user_id, plan, now, day))
        row = await repo.create_session(
            user_id, day, (SESSION_VERSION, int(plan["plan_version"])), steps)
    view = await session_view.render(repo, user_id, row, now)
    await repo.commit()
    return view


async def _load(repo: SessionRepo, user_id: UUID, session_id: UUID,
                step_no: int | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    row = await repo.get_session_by_id(user_id, session_id)
    if row is None:
        raise NotFound("session not found")
    if step_no is None:
        return row, None
    step = next((s for s in row["steps"] if int(s["step_no"]) == step_no), None)
    if step is None:
        raise NotFound("step not found")
    if row["status"] == "completed":
        raise StepClosed("this session is already complete")
    return row, step


async def _finish(repo: SessionRepo, user_id: UUID, session_id: UUID,
                  now: datetime) -> dict[str, Any]:
    row = await repo.get_session_by_id(user_id, session_id)
    assert row is not None
    view = await session_view.render(repo, user_id, row, now)
    await repo.commit()
    return view


def _start_changes(step: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    if step["started_at"] is not None:
        return {}
    changes: dict[str, Any] = {"status": "active", "started_at": now}
    if step["kind"] == "test":
        minutes = int(step["payload"].get("time_limit_minutes") or step["minutes"] or 1)
        changes["deadline_at"] = now + timedelta(minutes=minutes)
    return changes


async def start_step(repo: SessionRepo, user_id: UUID, session_id: UUID, step_no: int,
                     now: datetime) -> dict[str, Any]:
    """Start a step (idempotent); a test step's clock starts here."""
    _, step = await _load(repo, user_id, session_id, step_no)
    assert step is not None
    if step["status"] == "pending":
        await repo.update_step(user_id, session_id, step_no, _start_changes(step, now))
    return await _finish(repo, user_id, session_id, now)


async def complete_step(repo: SessionRepo, user_id: UUID, session_id: UUID, step_no: int,
                        now: datetime, skip: bool = False) -> dict[str, Any]:
    _, step = await _load(repo, user_id, session_id, step_no)
    assert step is not None
    if step["status"] not in ("done", "skipped"):
        changes = {**_start_changes(step, now), "completed_at": now,
                   "status": "skipped" if skip else "done"}
        await repo.update_step(user_id, session_id, step_no, changes)
    return await _finish(repo, user_id, session_id, now)


async def _answer_sba(repo: SessionRepo, user_id: UUID, session_id: UUID,
                      step: Mapping[str, Any], body: Mapping[str, Any], now: datetime) -> None:
    ids = [str(i) for i in step["payload"].get("question_ids", [])]
    qid = str(body.get("question_id") or "")
    if qid not in ids or body.get("selected_option") is None:
        raise Invalid("answer a question of this step with selected_option")
    result = dict(step.get("result") or {})
    answers = dict(result.get("answers") or {})
    if qid in answers:
        return  # idempotent: the first answer stands
    started = _start_changes(step, now)
    deadline = started.get("deadline_at") or step["deadline_at"]
    if deadline is not None and now > deadline + GRACE:
        raise StepClosed("time is up for this block")
    if await repo.question_locked(user_id, UUID(qid)):
        raise StepClosed("question is in an open exam")
    question = (await repo.questions_by_ids(user_id, [UUID(qid)])).get(qid)
    if question is None:
        raise NotFound("question not found")
    try:
        graded = grade_sba(question, int(body["selected_option"]))
    except InvalidAnswer as exc:
        raise Invalid(str(exc)) from exc
    attempt = await repo.record_sba(user_id, question, graded, body.get("confidence"),
                                    session_id, now)
    answers[qid] = {"selected_option": graded["selected_option"], "correct": graded["correct"],
                    "confidence": body.get("confidence"),
                    "attempt_id": None if attempt is None else str(attempt)}
    changes: dict[str, Any] = {**started, "result": {**result, "answers": answers}}
    if len(answers) >= len(ids):
        changes.update(status="done", completed_at=now)
    await repo.update_step(user_id, session_id, int(step["step_no"]), changes)


async def _answer_viva(repo: SessionRepo, user_id: UUID, session_id: UUID,
                       step: Mapping[str, Any], text: str, now: datetime) -> Grading | None:
    if (step.get("result") or {}).get("answer_text"):
        return None  # idempotent: the first answer stands
    payload = step["payload"]
    result: dict[str, Any] = {"answer_text": text}
    grading = None
    if payload.get("mode") == "graded":
        qid = str(payload.get("question_id"))
        if await repo.question_locked(user_id, UUID(qid)):
            raise StepClosed("question is in an open exam")
        question = (await repo.questions_by_ids(user_id, [UUID(qid)])).get(qid)
        if question is None:
            raise NotFound("question not found")
        exam = await repo.submit_viva(user_id, question, text)
        if exam is not None:
            result["exam_id"] = str(exam["id"])
            grading = Grading(exam["id"], pending_ids(exam.get("result")))
    changes = {**_start_changes(step, now), "result": result, "status": "done",
               "completed_at": now}
    await repo.update_step(user_id, session_id, int(step["step_no"]), changes)
    return grading


async def answer(repo: SessionRepo, user_id: UUID, session_id: UUID, step_no: int,
                 body: Mapping[str, Any], now: datetime) -> tuple[dict[str, Any], Grading | None]:
    """Record an SBA or viva answer for a step; returns the view and any grading to queue."""
    _, step = await _load(repo, user_id, session_id, step_no)
    assert step is not None
    if step["status"] == "skipped":
        raise StepClosed("this step was skipped")
    grading = None
    if step["kind"] == "test":
        await _answer_sba(repo, user_id, session_id, step, body, now)
    elif step["kind"] == "viva":
        text = str(body.get("answer_text") or "").strip()
        if not text:
            raise Invalid("answer_text is required")
        grading = await _answer_viva(repo, user_id, session_id, step, text, now)
    else:
        raise Invalid("this step takes no answers")
    return await _finish(repo, user_id, session_id, now), grading


async def complete_session(repo: SessionRepo, user_id: UUID, session_id: UUID,
                           now: datetime) -> dict[str, Any]:
    """Freeze the summary once (idempotent) and let tomorrow's plan rebuild."""
    row, _ = await _load(repo, user_id, session_id)
    if row["status"] != "completed":
        for step in row["steps"]:
            if step["status"] not in ("done", "skipped"):
                await repo.update_step(user_id, session_id, int(step["step_no"]),
                                       {"status": "skipped", "completed_at": now})
        steps = (await _load(repo, user_id, session_id))[0]["steps"]
        profile = await require_profile(repo, user_id)
        counts = await repo.counts(user_id, now, row["created_at"])
        rows, _ = await topic_rows(repo, user_id, now, profile)
        coverage = weighted_coverage([Topic(r.weight, r.mastery.coverage) for r in rows])
        summary = summarize(steps, counts["reviews_today"], coverage)
        await repo.finish_session(user_id, session_id, summary, now)
        await repo.delete_plans_from(user_id, row["session_date"] + timedelta(days=1))
    return await _finish(repo, user_id, session_id, now)
