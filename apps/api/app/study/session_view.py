"""Render a stored Today session for the API: live cards, passages, questions, results.

Session rows hold ids and the user's own answers; everything shown is read live
under the caller's RLS context and carries its citation. Question keys and
explanations appear only for items the user has already answered (the same
rule as the assessment API), and viva results appear once graded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.assessment.contracts import public_question
from apps.api.app.study.ports import SessionRepo
from apps.api.app.study.service import citation_for
from packages.assessment.grading import grade_sba
from packages.study.session import current_step

PASSAGE_CHARS = 2400
NOTICE = ("Every card, passage, question and answer links to its source. "
          "No pass probability is shown until it has been validated.")


def _uuids(values: Sequence[Any]) -> list[UUID]:
    out: list[UUID] = []
    for value in values:
        try:
            out.append(UUID(str(value)))
        except ValueError:
            continue
    return out


async def _review(repo: SessionRepo, user_id: UUID, session: Mapping[str, Any],
                  step: Mapping[str, Any]) -> dict[str, Any]:
    cards = await repo.cards_by_ids(user_id, _uuids(step["payload"].get("card_ids", [])))
    since: datetime = session["created_at"]
    pending = [c for c in cards if c["last_review_at"] is None or c["last_review_at"] < since]
    return {"total": len(cards), "reviewed": len(cards) - len(pending), "cards": pending}


def _figure(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "figure_id": row["id"], "caption": row["caption"], "description": row["description"],
        "modality": row["modality"],
        "image_path": f"/v1/library/figures/{row['id']}/image" if row["has_image"] else None,
        "citation": {"kind": "figure", "figure_id": str(row["id"]),
                     "source_id": str(row["source_id"]), "source_title": row["source_title"],
                     "page_from": row["page_no"], "page_to": row["page_no"]},
    }


async def _learn(repo: SessionRepo, user_id: UUID, step: Mapping[str, Any]) -> dict[str, Any]:
    payload = step["payload"]
    ids = _uuids(payload.get("chunk_ids", []))
    chunks = await repo.chunks_for_user(user_id, None, ids, len(ids)) if ids else []
    by_id = {str(c["id"]): c for c in chunks}
    figures = await repo.figures_by_ids(user_id, _uuids(payload.get("figure_ids", [])))
    return {
        "topic": payload.get("topic"),
        "chunks": [{"chunk_id": c["id"], "heading": c["heading"],
                    "text": str(c["text"])[:PASSAGE_CHARS], "citation": citation_for(c)}
                   for c in (by_id[str(i)] for i in ids if str(i) in by_id)],
        "figures": [_figure(f) for f in figures],
    }


def _feedback(question: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, Any]:
    graded = grade_sba(question, answer.get("selected_option"))
    return {**{k: graded[k] for k in ("question_id", "selected_option", "key", "correct",
                                       "explanation", "option_explanations", "citations")},
            "confidence": answer.get("confidence")}


async def _test(repo: SessionRepo, user_id: UUID, step: Mapping[str, Any]) -> dict[str, Any]:
    payload = step["payload"]
    ids = [str(i) for i in payload.get("question_ids", [])]
    found = await repo.questions_by_ids(user_id, _uuids(ids))
    answers: dict[str, Any] = dict((step.get("result") or {}).get("answers") or {})
    results = [_feedback(found[q], answers[q]) for q in ids if q in answers and q in found]
    return {
        "time_limit_minutes": int(payload.get("time_limit_minutes") or 0),
        "total": len(ids), "answered": len(answers),
        "correct": sum(1 for a in answers.values() if a.get("correct")),
        "retests": len(payload.get("retest_event_ids") or []),
        "questions": [public_question(found[q]).model_dump(mode="json")
                      for q in ids if q in found],
        "results": results,
    }


def _graded_item(exam: Mapping[str, Any] | None) -> dict[str, Any] | None:
    items = ((exam or {}).get("result") or {}).get("items") or []
    return dict(items[0]) if items else None


async def _viva_graded(repo: SessionRepo, user_id: UUID, payload: Mapping[str, Any],
                       result: Mapping[str, Any]) -> dict[str, Any]:
    qid = str(payload.get("question_id"))
    found = await repo.questions_by_ids(user_id, _uuids([qid]))
    view: dict[str, Any] = {
        "question": public_question(found[qid]).model_dump(mode="json") if qid in found
        else None, "status": "unanswered"}
    if not result.get("answer_text"):
        return view
    exam_id = _uuids([result.get("exam_id")])
    item = _graded_item(await repo.viva_exam(user_id, exam_id[0]) if exam_id else None)
    view["status"] = str(item.get("status", "pending")) if item else "pending"
    if item and item.get("status") == "graded":
        view["result"] = {k: item.get(k) for k in ("score", "max_score", "feedback", "points",
                                                   "model_answer", "key_findings")}
    view["citations"] = list(item.get("citations") or []) if item else []
    return view


async def _viva(repo: SessionRepo, user_id: UUID, step: Mapping[str, Any]) -> dict[str, Any]:
    payload, result = step["payload"], step.get("result") or {}
    base = {"mode": payload.get("mode"), "topic": payload.get("topic"),
            "prompt": payload.get("prompt"), "answer_text": result.get("answer_text"),
            "question": None, "status": "unanswered", "citations": [], "result": None,
            "reference": None}
    if payload.get("mode") == "graded":
        graded = await _viva_graded(repo, user_id, payload, result)
        return {**base, **graded}
    ref = _uuids([payload.get("reference_chunk_id")])
    chunks = await repo.chunks_for_user(user_id, None, ref, 1) if ref else []
    citations = [citation_for(chunks[0])] if chunks else []
    answered = bool(result.get("answer_text"))
    reference = ({"heading": chunks[0]["heading"],
                  "text": str(chunks[0]["text"])[:PASSAGE_CHARS]} if answered and chunks
                 else None)
    return {**base, "status": "self_review" if answered else "unanswered",
            "citations": citations, "reference": reference}


async def _step(repo: SessionRepo, user_id: UUID, session: Mapping[str, Any],
                step: Mapping[str, Any]) -> dict[str, Any]:
    view = {k: step.get(k) for k in ("step_no", "kind", "status", "minutes", "started_at",
                                     "deadline_at", "completed_at")}
    view.update(review=None, learn=None, test=None, viva=None)
    kind = step["kind"]
    if kind == "review":
        view["review"] = await _review(repo, user_id, session, step)
    elif kind == "learn":
        view["learn"] = await _learn(repo, user_id, step)
    elif kind == "test":
        view["test"] = await _test(repo, user_id, step)
    else:
        view["viva"] = await _viva(repo, user_id, step)
    return view


async def render(repo: SessionRepo, user_id: UUID, session: Mapping[str, Any],
                 now: datetime) -> dict[str, Any]:
    steps = list(session["steps"])
    finished = sum(1 for s in steps if s["status"] in ("done", "skipped"))
    return {
        **{k: session[k] for k in ("id", "session_date", "session_version", "plan_version",
                                   "status", "summary", "created_at", "completed_at")},
        "server_time": now,
        "current_step": current_step(steps),
        "progress": {"done": finished, "total": len(steps)},
        "steps": [await _step(repo, user_id, session, s) for s in steps],
        "notice": NOTICE,
    }
