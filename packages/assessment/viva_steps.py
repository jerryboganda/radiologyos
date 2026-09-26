"""One unit of examiner work for a viva or staged image-case session (no database).

The worker snapshots the session in a transaction, calls ``run_step`` outside
any transaction, and applies the returned ``StepOutcome`` in a second one.
Work is keyed by (session, turn number, ``PIPELINE_VERSION``): turn 0 opens a
viva or prepares a staged case; turn n grades the answer to turn n and asks
turn n+1 or finishes. Model output that fails the citation rules is treated
like a model error (retried, then the session stops), never shown uncited.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from packages.assessment import agents, viva_agents
from packages.assessment.staged_case import (
    STAGE_PROMPTS,
    STAGES,
    flattened_item,
    stage_evaluation,
    stage_question,
    stage_rubric,
    validate_staged,
    with_stages,
)
from packages.assessment.validation import Excerpt, stored_parts
from packages.assessment.viva import (
    StopReason,
    citation_map,
    cited_expected,
    evaluate_turn,
    next_move,
    resolve_supplied,
    stop_reason,
)
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import Transport

MAX_ERRORS = 3
MAX_RUNS = 48
STAGES_AGENT = "image_case_stages/v1"
CHECKER = "question_check/v1"
EXAM_TAG = {"practice": "fcps2_toacs", "fcps2_toacs": "fcps2_toacs", "frcr_2b_oral": "frcr"}
OutcomeKind = Literal["applied", "deferred", "retry", "failed"]


class UncitedOutput(ModelCallError):
    """Model output that would put uncited examiner text in front of the candidate."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    kind: str
    style: str
    topic: str
    scenario: str
    level: int
    miss_streak: int
    max_turns: int
    deadline_at: datetime | None
    case_data: Mapping[str, Any]
    evidence: Sequence[Excerpt]
    turns: Sequence[Mapping[str, Any]]
    work_turn: int
    errors: int
    runs: int


@dataclass(slots=True)
class StepOutcome:
    kind: OutcomeKind
    error: str | None = None
    session: dict[str, Any] = field(default_factory=dict)
    graded: dict[str, Any] | None = None  # {"turn_no", "evaluation"}
    new_turn: dict[str, Any] | None = None
    finish: StopReason | None = None
    question: dict[str, Any] | None = None


def run_step(transport: Transport | None, snap: Snapshot, now: datetime) -> StepOutcome:
    """Do the model work for ``snap.work_turn``; errors become retry/defer/fail outcomes."""
    if transport is None:
        return _pause(snap, "model_unavailable")
    try:
        if snap.work_turn == 0:
            return _open(transport, snap) if snap.kind == "viva" else _prepare(transport, snap)
        if snap.kind == "viva":
            return _grade_viva(transport, snap, now)
        return _grade_stage(transport, snap, now)
    except UsageLimitError:
        return _pause(snap, "usage_limit")
    except ModelCallError as exc:
        code = "uncited_output" if isinstance(exc, UncitedOutput) else "model_error"
        if snap.errors + 1 >= MAX_ERRORS:
            return StepOutcome("failed", error=code)
        return StepOutcome("retry", error=code)


def _pause(snap: Snapshot, code: str) -> StepOutcome:
    if snap.runs + 1 >= MAX_RUNS:
        return StepOutcome("failed", error=f"{code}_exhausted")
    return StepOutcome("deferred", error=code)


def _turn(turn_no: int, level: int, move: str, prompt: str, expected: list[dict[str, Any]],
          hint: str = "", stage: str | None = None) -> dict[str, Any]:
    return {"turn_no": turn_no, "level": level, "move": move, "prompt": prompt.strip(),
            "hint": hint.strip(), "expected": expected, "stage": stage}


def _open(transport: Transport, snap: Snapshot) -> StepOutcome:
    opening = viva_agents.open_viva(transport, snap.evidence, snap.style, snap.topic, snap.level)
    by_ref = citation_map(snap.evidence)
    expected = cited_expected(opening.question, by_ref)
    cites = resolve_supplied(opening.citations, by_ref)
    if not expected or not cites or not opening.question.question.strip():
        raise UncitedOutput("opening question is not cited to supplied excerpts")
    session = {"status": "active", "scenario": opening.scenario.strip(),
               "case_data": {"scenario_citations": cites},
               "topic": snap.topic or opening.topic.strip()[:300]}
    return StepOutcome("applied", session=session,
                       new_turn=_turn(1, snap.level, "open", opening.question.question, expected))


def _staged_row(snap: Snapshot, transport: Transport) -> tuple[dict[str, Any], list[Any]]:
    case = viva_agents.write_stages(transport, snap.evidence, snap.style, snap.topic)
    if validate_staged(case, [e.ref for e in snap.evidence]):
        raise UncitedOutput("staged case failed the deterministic checks")
    item = flattened_item(case)
    rubric = stage_rubric(case, snap.evidence)
    try:
        verdict = agents.check(transport, item, snap.evidence)
    except UsageLimitError:
        raise
    except ModelCallError:
        verdict = None
    passed = verdict is not None and verdict.passed
    parts = stored_parts(item, snap.evidence)
    parts["answer"] = with_stages(parts["answer"], rubric)
    row = {
        "type": "image_case", "exam_tags": [EXAM_TAG[snap.style]], "topic": case.topic,
        "stem": case.stem, "explanation": item.explanation,
        "status": "active" if passed else "draft", "agent_version": f"{STAGES_AGENT}+{CHECKER}",
        "quality": {"deterministic": "pass", "checker": CHECKER, "passed": passed,
                    "check": verdict.model_dump() if verdict else {"error": "check_failed"},
                    "difficulty": item.difficulty, "cognitive_level": item.cognitive_level},
        **parts,
    }
    return row, rubric


def _prepare(transport: Transport, snap: Snapshot) -> StepOutcome:
    row, rubric = _staged_row(snap, transport)
    session = {"status": "active", "scenario": row["stem"], "topic": row["topic"][:300],
               "case_data": {"stages": rubric}}
    first = rubric[0]
    return StepOutcome("applied", session=session, question=row,
                       new_turn=_turn(1, 1, "stage", STAGE_PROMPTS[first["stage"]],
                                      first["marking_scheme"], stage=first["stage"]))


def _current(snap: Snapshot) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    current = next(t for t in snap.turns if t["turn_no"] == snap.work_turn)
    earlier = [t for t in snap.turns if t["turn_no"] < snap.work_turn and t.get("evaluation")]
    return current, earlier


def _grade_viva(transport: Transport, snap: Snapshot, now: datetime) -> StepOutcome:
    current, earlier = _current(snap)
    answer = str(current.get("answer_text") or "")
    grade = viva_agents.grade_turn(transport, snap.evidence, snap.style, snap.scenario,
                                   earlier, current, answer)
    by_ref = citation_map(snap.evidence)
    evaluation = evaluate_turn(grade, current["expected"], by_ref)
    move = next_move(evaluation["verdict"], int(current["level"]), snap.miss_streak)
    graded = {"turn_no": snap.work_turn, "evaluation": {**evaluation, "move": move.kind}}
    session = {"level": move.level, "miss_streak": move.miss_streak}
    stop = stop_reason(len(earlier) + 1, snap.max_turns, move.miss_streak, now, snap.deadline_at)
    if stop is not None:
        return StepOutcome("applied", session=session, graded=graded, finish=stop)
    question = grade.escalate if move.kind == "escalate" else grade.probe
    expected = cited_expected(question, by_ref)
    if not expected or not question.question.strip():
        raise UncitedOutput("next examiner question is not cited to supplied excerpts")
    hint = question.hint if move.kind == "probe" else ""
    turn = _turn(snap.work_turn + 1, move.level, move.kind, question.question, expected, hint)
    return StepOutcome("applied", session=session, graded=graded, new_turn=turn)


def _grade_stage(transport: Transport, snap: Snapshot, now: datetime) -> StepOutcome:
    current, _ = _current(snap)
    rubrics = {r["stage"]: r for r in snap.case_data.get("stages", [])}
    rubric = rubrics[str(current["stage"])]
    grade = agents.grade_free_text(transport, stage_question(snap.scenario, rubric),
                                   str(current.get("answer_text") or ""))
    graded = {"turn_no": snap.work_turn, "evaluation": stage_evaluation(rubric, grade)}
    position = STAGES.index(str(current["stage"]))
    if position + 1 >= len(STAGES) or str(current["stage"]) == list(rubrics)[-1]:
        return StepOutcome("applied", graded=graded, finish="stages_complete")
    if snap.deadline_at is not None and now >= snap.deadline_at:
        return StepOutcome("applied", graded=graded, finish="time_up")
    nxt = rubrics[STAGES[position + 1]]
    turn = _turn(snap.work_turn + 1, 1, "stage", STAGE_PROMPTS[nxt["stage"]],
                 nxt["marking_scheme"], stage=nxt["stage"])
    return StepOutcome("applied", graded=graded, new_turn=turn)
