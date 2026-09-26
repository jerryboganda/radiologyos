"""Request/response contracts for viva sessions and staged image cases.

``session_view`` is the only way a session leaves the API. An examiner's
frozen expected points (the answer) are shown for a turn only once that turn
is graded or the session has ended, so the transcript never hands the
candidate the answer to the question in front of them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from packages.assessment.staged_case import STAGE_LABELS
from pydantic import BaseModel, ConfigDict, Field, model_validator

VivaKind = Literal["viva", "image_case"]
VivaStyle = Literal["practice", "fcps2_toacs", "frcr_2b_oral"]
DEFAULT_TURNS: dict[str, int] = {"practice": 8, "fcps2_toacs": 6, "frcr_2b_oral": 10}
STAGE_COUNT = 5


class VivaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: VivaKind = "viva"
    style: VivaStyle = "practice"
    topic: str | None = Field(default=None, min_length=2, max_length=200)
    figure_id: UUID | None = None
    question_id: UUID | None = None
    max_turns: int | None = Field(default=None, ge=2, le=20)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def require_scope(self) -> VivaCreate:
        if self.question_id is not None and self.kind != "image_case":
            raise ValueError("question_id starts a staged image case only")
        if not (self.topic or self.figure_id or self.question_id):
            raise ValueError("give a topic, a figure_id, or a question_id")
        return self

    def turn_limit(self) -> int:
        if self.kind == "image_case":
            return STAGE_COUNT
        return self.max_turns or DEFAULT_TURNS[self.style]


class VivaAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_text: str = Field(min_length=1, max_length=8000)


class TurnView(BaseModel):
    turn_no: int
    stage: str | None
    stage_label: str | None
    level: int
    move: str
    prompt: str
    hint: str
    status: str
    answer_text: str | None
    answered_at: datetime | None
    expected: list[dict[str, Any]] = Field(default_factory=list)
    evaluation: dict[str, Any] | None = None


class SessionView(BaseModel):
    id: UUID
    kind: str
    style: str
    topic: str
    status: str
    work: str
    error_code: str | None
    scenario: str
    scenario_citations: list[dict[str, Any]]
    figure_id: UUID | None
    figure_image_path: str | None
    question_id: UUID | None
    level: int
    miss_streak: int
    max_turns: int
    started_at: datetime
    deadline_at: datetime | None
    finished_at: datetime | None
    server_time: datetime
    stop_reason: str | None
    current_turn: int | None
    turns: list[TurnView]
    debrief: dict[str, Any] | None


class SessionSummary(BaseModel):
    id: UUID
    kind: str
    style: str
    topic: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stop_reason: str | None
    overall_percent: float | None


def _turn_view(turn: Mapping[str, Any], ended: bool) -> TurnView:
    reveal = ended or turn["status"] == "graded"
    stage = turn.get("stage")
    return TurnView(
        turn_no=turn["turn_no"], stage=stage, stage_label=STAGE_LABELS.get(stage or ""),
        level=turn["level"], move=turn["move"], prompt=turn["prompt"], hint=turn["hint"],
        status=turn["status"], answer_text=turn.get("answer_text"),
        answered_at=turn.get("answered_at"),
        expected=list(turn["expected"]) if reveal else [],
        evaluation=turn.get("evaluation") if turn["status"] == "graded" else None,
    )


def session_view(row: Mapping[str, Any], turns: Sequence[Mapping[str, Any]],
                 now: datetime) -> SessionView:
    ended = row["status"] in ("finished", "failed")
    asked = [t["turn_no"] for t in turns if t["status"] == "asked"]
    figure_id = row.get("figure_id")
    return SessionView(
        id=row["id"], kind=row["kind"], style=row["style"], topic=row["topic"],
        status=row["status"], work=row["work"], error_code=row.get("error_code"),
        scenario=row["scenario"],
        scenario_citations=list((row.get("case_data") or {}).get("scenario_citations") or []),
        figure_id=figure_id,
        figure_image_path=f"/v1/library/figures/{figure_id}/image" if figure_id else None,
        question_id=row.get("question_id"), level=row["level"], miss_streak=row["miss_streak"],
        max_turns=row["max_turns"], started_at=row["started_at"],
        deadline_at=row.get("deadline_at"), finished_at=row.get("finished_at"),
        server_time=now, stop_reason=row.get("stop_reason"),
        current_turn=asked[-1] if asked and not ended else None,
        turns=[_turn_view(t, ended) for t in turns], debrief=row.get("debrief"),
    )


def session_summary(row: Mapping[str, Any]) -> SessionSummary:
    return SessionSummary(
        id=row["id"], kind=row["kind"], style=row["style"], topic=row["topic"],
        status=row["status"], started_at=row["started_at"], finished_at=row.get("finished_at"),
        stop_reason=row.get("stop_reason"),
        overall_percent=(row.get("debrief") or {}).get("overall_percent"),
    )
