"""Examiner steps with a fake transport: opening, escalation, stop rules, staged cases."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.tests.test_assessment_api import FakeTransport
from apps.api.tests.test_assessment_validation import EXCERPTS
from apps.api.tests.viva_fakes import (
    CHECK_PASS,
    NOW,
    grade,
    opening,
    seq_grade,
    snap,
    staged_case,
    viva_turn,
)
from evals.contracts import load_eval_fixtures
from packages.assessment.models import SeqGrade
from packages.assessment.staged_case import STAGE_PROMPTS
from packages.assessment.viva_models import StagedCase, VivaOpening, VivaTurnGrade
from packages.assessment.viva_steps import MAX_ERRORS, MAX_RUNS, run_step
from packages.library.parse_models import inline_schema
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import load_agent

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(("agent", "model"), [
    ("viva_open", VivaOpening), ("viva_examiner", VivaTurnGrade),
    ("image_case_stages", StagedCase),
])
def test_agents_are_versioned_with_generated_schemas(agent: str, model: Any) -> None:
    loaded = load_agent(agent)
    assert loaded.output_model is model and loaded.schema == inline_schema(model)
    assert (loaded.prompt.route.value, loaded.prompt.effort) == ("reason", "high")
    assert loaded.prompt.tools == () and loaded.prompt.fixture == "evals/fixtures/viva_v1.json"
    fixture = load_eval_fixtures(ROOT / loaded.prompt.fixture)
    assert fixture.data_class == "synthetic"
    assert any(case.prompt == f"{agent}/v1.yaml" for case in fixture.cases)
    stored = json.loads((ROOT / "packages/prompts" / loaded.prompt.output_schema).read_text())
    assert stored == inline_schema(model)


def test_opening_asks_a_cited_first_question() -> None:
    fake = FakeTransport({"viva_open": [opening()]})
    out = run_step(fake, snap(work_turn=0, turns=[], topic=""), NOW)
    assert out.kind == "applied" and out.session["status"] == "active"
    assert out.session["topic"] == "Pulmonary alveolar proteinosis"
    assert out.new_turn is not None and out.new_turn["turn_no"] == 1
    assert out.new_turn["move"] == "open" and len(out.new_turn["expected"]) == 2
    assert out.session["case_data"]["scenario_citations"][0]["ref"] == "F1"


def test_uncited_opening_fails_closed_and_retries() -> None:
    fake = FakeTransport({"viva_open": [opening(cite="E404")]})
    out = run_step(fake, snap(work_turn=0, turns=[]), NOW)
    assert (out.kind, out.error, out.new_turn) == ("retry", "uncited_output", None)
    last = run_step(FakeTransport({"viva_open": [opening(cite="E404")]}),
                    snap(work_turn=0, turns=[], errors=MAX_ERRORS - 1), NOW)
    assert last.kind == "failed"


def test_good_answer_escalates_with_the_escalate_question() -> None:
    out = run_step(FakeTransport({"viva_examiner": [grade()]}),
                   snap(turns=[viva_turn(1, level=2)]), NOW)
    assert out.graded is not None and out.graded["evaluation"]["verdict"] == "good"
    assert out.session == {"level": 3, "miss_streak": 0}
    assert out.new_turn is not None and out.new_turn["move"] == "escalate"
    assert out.new_turn["prompt"] == "Give three differentials." and out.new_turn["hint"] == ""
    assert out.new_turn["level"] == 3 and out.finish is None


def test_weak_answer_probes_with_a_hint() -> None:
    out = run_step(FakeTransport({"viva_examiner": [grade(("partial", "missed"))]}),
                   snap(turns=[viva_turn(1, level=2)]), NOW)
    assert out.new_turn is not None and out.new_turn["move"] == "probe"
    assert out.new_turn["hint"] == "Consider the interlobular septa."
    assert out.session == {"level": 1, "miss_streak": 1}


def test_second_consecutive_miss_stops_with_the_teaching_point() -> None:
    out = run_step(FakeTransport({"viva_examiner": [grade(("missed", "missed"))]}),
                   snap(miss_streak=1), NOW)
    assert out.finish == "two_consecutive_misses" and out.new_turn is None
    assert out.graded is not None and out.graded["evaluation"]["teaching_point"]["citations"]


def test_turn_limit_and_deadline_stop_the_viva() -> None:
    earlier = viva_turn(1, "graded", evaluation={"verdict": "good"})
    at_limit = snap(max_turns=2, turns=[earlier, viva_turn(2)], work_turn=2)
    assert run_step(FakeTransport({"viva_examiner": [grade()]}), at_limit, NOW).finish == \
        "max_turns"
    late = snap(deadline_at=NOW - timedelta(seconds=1))
    assert run_step(FakeTransport({"viva_examiner": [grade()]}), late, NOW).finish == "time_up"


def test_uncited_next_question_is_never_asked() -> None:
    out = run_step(FakeTransport({"viva_examiner": [grade(escalate_cite="E404")]}), snap(), NOW)
    assert (out.kind, out.error, out.new_turn) == ("retry", "uncited_output", None)


def test_model_failures_pause_retry_and_give_up() -> None:
    assert run_step(None, snap(), NOW).kind == "deferred"
    assert run_step(None, snap(runs=MAX_RUNS - 1), NOW).error == "model_unavailable_exhausted"
    limited = FakeTransport({"viva_examiner": [UsageLimitError("limit")]})
    assert run_step(limited, snap(), NOW).error == "usage_limit"
    broken = FakeTransport({"viva_examiner": [ModelCallError("boom")]})
    assert run_step(broken, snap(), NOW).kind == "retry"


def test_staged_case_preparation_stores_a_checked_bank_question() -> None:
    fake = FakeTransport({"image_case_stages": [staged_case()], "question_check": [CHECK_PASS]})
    out = run_step(fake, snap(kind="image_case", work_turn=0, turns=[]), NOW)
    assert out.kind == "applied" and out.question is not None
    assert out.question["status"] == "active" and out.question["figure_id"] == EXCERPTS[0].figure_id
    assert [s["stage"] for s in out.question["answer"]["stages"]][0] == "describe"
    assert all(p["stage"] for p in out.question["answer"]["marking_scheme"])
    assert out.new_turn is not None and out.new_turn["prompt"] == STAGE_PROMPTS["describe"]
    assert out.session["case_data"]["stages"][4]["stage"] == "next_step"


def test_staged_case_with_checker_error_is_kept_as_draft() -> None:
    fake = FakeTransport({"image_case_stages": [staged_case()],
                          "question_check": [ModelCallError("boom")]})
    out = run_step(fake, snap(kind="image_case", work_turn=0, turns=[]), NOW)
    assert out.question is not None and out.question["status"] == "draft"
    bad = FakeTransport({"image_case_stages": [staged_case(cite="E404")]})
    assert run_step(bad, snap(kind="image_case", work_turn=0, turns=[]), NOW).kind == "retry"


def _staged_snap(stage: str, work_turn: int) -> Any:
    case = StagedCase.model_validate(staged_case())
    from packages.assessment.staged_case import stage_rubric

    rubric = stage_rubric(case, EXCERPTS)
    turn = {**viva_turn(work_turn), "stage": stage, "move": "stage"}
    return snap(kind="image_case", case_data={"stages": rubric}, turns=[turn],
                work_turn=work_turn)


def test_each_stage_is_graded_then_the_next_is_asked() -> None:
    fake = FakeTransport({"seq_grade": [seq_grade(1.0)]})
    out = run_step(fake, _staged_snap("findings", 2), NOW)
    assert out.graded is not None and out.graded["evaluation"]["score"] == 1.0
    assert out.graded["evaluation"]["model_answer"] == "findings answer"
    assert out.new_turn is not None and out.new_turn["stage"] == "diagnosis"
    SeqGrade.model_validate(seq_grade())


def test_last_stage_finishes_the_case() -> None:
    out = run_step(FakeTransport({"seq_grade": [seq_grade()]}), _staged_snap("next_step", 5), NOW)
    assert out.finish == "stages_complete" and out.new_turn is None


def test_migration_is_expand_only_with_forced_rls_and_registered() -> None:
    from apps.worker.app.datarights.registry import DIRECT_DELETE_ORDER, owned

    source = (ROOT / "apps/api/migrations/versions/20260926_0018_viva_sessions.py").read_text(
        encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    assert 'revision = "20260926_0018"' in source
    assert 'TABLES = ("viva_sessions", "viva_turns")' in upgrade
    for statement in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                      "tenant_id = app.current_tenant_id()", "REVOKE ALL ON {table} FROM PUBLIC",
                      "REFERENCES viva_sessions(tenant_id, id)"):
        assert statement in upgrade
    assert "DROP " not in upgrade and "RENAME" not in upgrade and "ALTER TABLE questions" \
        not in upgrade
    assert "SECURITY DEFINER" not in upgrade and "text jsonb" not in upgrade
    for table in ("viva_sessions", "viva_turns"):
        assert owned(table).erased_by == "direct"
    order = list(DIRECT_DELETE_ORDER)
    assert order.index("viva_turns") < order.index("viva_sessions") < order.index("questions")
