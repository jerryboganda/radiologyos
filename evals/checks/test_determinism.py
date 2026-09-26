"""Determinism gate: fixed inputs and a fixed clock give byte-identical durable output.

Replaces ``test_preview_determinism.py``. The rules-based planner
(``packages/study/planner.py``, and the study service that feeds it), the
Today session builder (``packages/study/session.py``, seeded per user and day),
the served question view (``public_question``), mock-paper assembly
(``packages/assessment/paper.py``), and exam grading must each render to the
same bytes on every run, so a plan, a paper, or a score can be reproduced and
audited. Nothing here calls a model or a database.

Paper *selection* is random on purpose in production (``ORDER BY random()`` for
ad-hoc papers, ``secrets.randbits`` as the blueprint seed), so a learner gets a
fresh paper each time; what is pinned here is that assembly is a pure function
of its seed and that everything served from a given paper is reproducible.

All content is synthetic.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.assessment.contracts import public_question
from apps.api.app.study import service
from apps.api.tests.study_fakes import MemoryStudyRepo
from evals.checks._m5_support import Harness, question_row
from packages.assessment.blueprints import MixGroup
from packages.assessment.exam_result import grade_exam
from packages.assessment.grading import ExamState
from packages.assessment.paper import PaperCandidate, assemble
from packages.study.planner import DayInputs, TopicSignal, build_plan
from packages.study.session import Retest, SbaCandidate, SessionInputs, VivaChoice, build_steps

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
OWNER = UUID("10000000-0000-4000-8000-0000000000d1")
SYSTEMS = ("CHEST", "NEURO", "GI", "MUSCULOSKELETAL", "GU")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()


def _topics() -> list[TopicSignal]:
    return [TopicSignal(code, code.title(), mastery=0.1 * i, recent_lapse=i == 2,
                        days_untouched=None if i == 0 else 5 * i)
            for i, code in enumerate(SYSTEMS)]


@pytest.mark.parametrize("days", [400, 120, 60, 20, 3])
def test_the_planner_is_byte_identical_for_fixed_inputs(days: int) -> None:
    def plan() -> bytes:
        return _bytes(build_plan(DayInputs(
            today=NOW.date(), exam_date=NOW.date() + timedelta(days=days), minutes=90,
            due_count=17, new_available=30, topics=_topics(), exam_targets=("frcr",))))

    assert plan() == plan()


class _PinnedRepo(MemoryStudyRepo):
    """Stamps saved plans with the fixed clock instead of the wall clock."""

    async def save_plan(self, user_id: UUID, plan: dict[str, Any]) -> datetime:
        await super().save_plan(user_id, plan)
        self.plans[(user_id, date.fromisoformat(plan["plan_date"]))]["generated_at"] = NOW
        return NOW


async def _study_run() -> tuple[bytes, bytes]:
    repo = _PinnedRepo()
    profile = {"exam_date": NOW.date() + timedelta(days=75), "exam_targets": ["fcps2_theory"],
               "daily_minutes": 75, "weekday_minutes": None, "weekend_minutes": None,
               "timezone": "Asia/Karachi"}
    await service.save_profile(repo, OWNER, profile, NOW)
    repo.weights.append((OWNER, {"exam_target": "fcps2_theory", "curriculum_code": "CHEST",
                                 "weight": 0.6}))
    for code in ("CHEST", "NEURO", "CHEST"):
        chunk = repo.add_chunk(OWNER)
        fields = {"chunk_id": chunk, "curriculum_code": code, "topic": "t", "front": "f",
                  "back": "b"}
        card = await service.create_card(repo, OWNER, fields, NOW - timedelta(days=4))
        await service.review_card(repo, OWNER, card["id"], 3, NOW - timedelta(days=4))
    plan = await service.today_plan(repo, OWNER, NOW)
    progress = await service.progress(repo, OWNER, NOW)
    return _bytes(plan), _bytes(progress)


def test_the_study_service_plan_and_progress_are_byte_identical() -> None:
    first, second = asyncio.run(_study_run()), asyncio.run(_study_run())
    assert first == second


def _session_inputs(seed: int) -> SessionInputs:
    plan = build_plan(DayInputs(
        today=NOW.date(), exam_date=NOW.date() + timedelta(days=60), minutes=90, due_count=4,
        new_available=10, topics=_topics()))
    candidates = [SbaCandidate(f"q{i:02d}", SYSTEMS[i % len(SYSTEMS)],
                               None if i % 3 else float(i)) for i in range(40)]
    return SessionInputs(
        plan=plan, card_ids=["c1", "c2", "c1"], topic={"code": "CHEST", "title": "Chest"},
        chunk_ids=["k1", "k2"], figure_ids=["f1"], candidates=candidates,
        retests=[Retest("e1", "q07"), Retest("e2", "q99")],
        viva=VivaChoice("self_review", reference_chunk_id="k1", prompt="Viva prompt."),
        seed=seed)


def test_the_session_builder_is_byte_identical_for_a_fixed_seed() -> None:
    first = build_steps(_session_inputs(seed=20260928))
    assert _bytes(first) == _bytes(build_steps(_session_inputs(seed=20260928)))
    test = next(step for step in first if step["kind"] == "test")
    assert test["payload"]["question_ids"][0] == "q07"  # open re-test first
    assert [step["step_no"] for step in first] == list(range(1, len(first) + 1))


def test_the_served_question_view_is_byte_identical() -> None:
    def views() -> bytes:
        return _bytes([public_question(question_row(i)).model_dump(mode="json")
                       for i in range(6)])

    assert views() == views()


def test_paper_assembly_and_grading_are_byte_identical_for_a_fixed_seed() -> None:
    candidates = [PaperCandidate(UUID(int=0xC000 + i), "sba" if i % 4 else "seq",
                                 SYSTEMS[i % len(SYSTEMS)], tagged=i % 2 == 0)
                  for i in range(60)]
    groups = [MixGroup(label="Chest and neuro", systems=("CHEST", "NEURO"), share=0.6),
              MixGroup(label="Abdomen", systems=("GI", "GU"), share=0.4)]

    def paper() -> tuple[bytes, list[tuple[UUID, str]]]:
        picks, report = assemble(candidates, {"sba": 20, "seq": 4}, groups, seed=7)
        return _bytes([picks, report]), picks

    (first, picks), (second, _) = paper(), paper()
    assert first == second and len(picks) == 24
    rows = {str(r["id"]): r for r in (question_row(i) for i in range(5))}
    exam = ExamState(mode="exam", question_ids=[UUID(q) for q in rows],
                     deadline_at=NOW + timedelta(minutes=30), submitted_at=None, revision=3,
                     answers={q: i for i, q in enumerate(rows)})
    assert _bytes(grade_exam(exam, rows)) == _bytes(grade_exam(exam, rows))


def test_the_served_exam_paper_is_byte_identical_over_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same bank, same picks, same clock: the listed views and the new exam view match."""

    def run() -> bytes:
        harness = Harness(monkeypatch)
        harness.seed(8)
        listed = harness.client.get("/v1/questions").json()
        exam = harness.client.post("/v1/exams", json={
            "mode": "exam", "count": 5, "time_limit_minutes": 30}).json()
        return _bytes([listed, exam])

    assert run() == run()
