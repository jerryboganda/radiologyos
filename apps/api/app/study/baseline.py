"""Baseline diagnostic use cases (``/v1/study/baseline``).

The baseline is an ordinary server-timed SBA exam (assessment engine, ADR 0015)
whose questions are picked round-robin across curriculum systems. The user
takes it on the exam page; submitting it writes graded ``attempts`` that feed
mastery accuracy, and the per-system summary is frozen on ``baseline_tests``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.study.ports import StudyRepo
from apps.api.app.study.service import StudyError
from apps.api.app.study.signals import curriculum_codes, curriculum_systems
from packages.study.baseline import (
    BASELINE_MIN,
    BASELINE_SIZE,
    Candidate,
    per_system,
    pick,
    time_limit_minutes,
)


class NotEnoughQuestions(StudyError):
    status_code = 409


class BaselineMissing(StudyError):
    status_code = 404


def _view(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    titles = {node.code: node.title for node in curriculum_systems()}
    systems: dict[str, str] = dict(row["systems"])
    if row["submitted_at"] is not None:
        status = "submitted"
    elif row["deadline_at"] is not None and now >= row["deadline_at"]:
        status = "expired"
    else:
        status = "open"
    return {
        "id": row["id"], "exam_id": row["exam_id"], "status": status,
        "question_count": len(row["question_ids"]),
        "systems": sorted(set(systems.values())),
        "started_at": row["started_at"], "deadline_at": row["deadline_at"],
        "submitted_at": row["submitted_at"],
        "results": [{**r, "title": titles.get(r["code"], r["code"])}
                    for r in (row["results"] or [])],
    }


async def _sync(repo: StudyRepo, user_id: UUID, row: dict[str, Any]) -> dict[str, Any]:
    """Freeze per-system results once the linked exam is submitted (or expired).

    Writes in the caller's transaction; the caller commits once at the end.
    """
    if row["submitted_at"] is not None:
        return row
    exam = await repo.baseline_exam(user_id, row["exam_id"])
    if exam is None or exam["submitted_at"] is None:
        return row
    results = per_system(exam["result"]["items"], dict(row["systems"]))
    await repo.finish_baseline(user_id, row["id"], exam["submitted_at"], results)
    return {**row, "submitted_at": exam["submitted_at"], "results": results}


async def latest(repo: StudyRepo, user_id: UUID, now: datetime) -> dict[str, Any]:
    row = await repo.latest_baseline(user_id)
    if row is None:
        raise BaselineMissing("no baseline test yet")
    view = _view(await _sync(repo, user_id, row), now)
    await repo.commit()
    return view


async def start(
    repo: StudyRepo, user_id: UUID, now: datetime, seed: int
) -> tuple[dict[str, Any], bool]:
    """Return the open baseline, or create one; the flag says whether it is new."""
    current = await repo.latest_baseline(user_id)
    if current is not None:
        current = await _sync(repo, user_id, current)
        if _view(current, now)["status"] == "open":
            await repo.commit()
            return _view(current, now), False
    known = curriculum_codes()
    candidates = [Candidate(UUID(str(r["question_id"])), str(r["curriculum_code"]))
                  for r in await repo.baseline_candidates(user_id)
                  if r["curriculum_code"] in known]
    if len(candidates) < BASELINE_MIN:
        await repo.commit()  # keep a just-finalised earlier baseline
        raise NotEnoughQuestions(
            f"a baseline needs at least {BASELINE_MIN} checked SBA questions linked to "
            f"curriculum systems; you have {len(candidates)}. Generate SBA questions from "
            "your library first.")
    chosen = pick(candidates, BASELINE_SIZE, seed)
    systems = {str(c.question_id): c.curriculum_code for c in chosen}
    row = await repo.create_baseline(user_id, systems, time_limit_minutes(len(chosen)), now)
    await repo.commit()
    return _view(row, now), True
