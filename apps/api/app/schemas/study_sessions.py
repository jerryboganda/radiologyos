"""Contracts for /v1/study/sessions (Today runner) and /v1/study/insights (progress).

Deliberately no pass-probability field anywhere (CLAUDE.md "Never").
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from apps.api.app.assessment.contracts import QuestionPublic
from apps.api.app.schemas.study import CardCitation, CardOut
from pydantic import BaseModel, ConfigDict, Field, model_validator

StepKind = Literal["review", "learn", "test", "viva"]
StepStatus = Literal["pending", "active", "done", "skipped"]


class TopicRef(BaseModel):
    code: str
    title: str


class ReviewStep(BaseModel):
    total: int
    reviewed: int
    cards: list[CardOut]


class LearnChunk(BaseModel):
    chunk_id: UUID
    heading: str
    text: str
    citation: CardCitation


class LearnFigure(BaseModel):
    figure_id: UUID
    caption: str
    description: str
    modality: str
    image_path: str | None
    citation: dict[str, Any]


class LearnStep(BaseModel):
    topic: TopicRef | None
    chunks: list[LearnChunk]
    figures: list[LearnFigure]


class SbaFeedback(BaseModel):
    question_id: UUID
    selected_option: int | None
    key: int
    correct: bool
    confidence: int | None = None
    explanation: str
    option_explanations: list[dict[str, Any]]
    citations: list[dict[str, Any]]


class SbaBlockStep(BaseModel):
    time_limit_minutes: int
    total: int
    answered: int
    correct: int
    retests: int = Field(description="Items re-testing an earlier wrong answer (weakness loop)")
    questions: list[QuestionPublic]
    results: list[SbaFeedback]


class VivaStep(BaseModel):
    mode: Literal["graded", "self_review"]
    topic: TopicRef | None
    prompt: str | None
    question: QuestionPublic | None
    answer_text: str | None
    status: Literal["unanswered", "pending", "graded", "failed", "self_review"]
    citations: list[dict[str, Any]]
    result: dict[str, Any] | None
    reference: dict[str, Any] | None


class SessionStep(BaseModel):
    step_no: int
    kind: StepKind
    status: StepStatus
    minutes: int
    started_at: datetime | None
    deadline_at: datetime | None
    completed_at: datetime | None
    review: ReviewStep | None = None
    learn: LearnStep | None = None
    test: SbaBlockStep | None = None
    viva: VivaStep | None = None


class SessionProgress(BaseModel):
    done: int
    total: int


class StudySessionOut(BaseModel):
    id: UUID
    session_date: date
    session_version: int
    plan_version: int
    status: Literal["active", "completed"]
    summary: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None
    server_time: datetime
    current_step: int | None
    progress: SessionProgress
    steps: list[SessionStep]
    notice: str


class StepAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: UUID | None = None
    selected_option: int | None = Field(default=None, ge=0, le=4)
    confidence: int | None = Field(default=None, ge=1, le=3,
                                   description="1 low, 2 medium, 3 high")
    answer_text: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode="after")
    def one_kind(self) -> StepAnswerIn:
        if (self.selected_option is None) == (self.answer_text is None):
            raise ValueError("give selected_option (SBA) or answer_text (viva)")
        return self


class HeatmapCell(BaseModel):
    code: str
    title: str
    material: int
    studied: int
    coverage: float | None
    accuracy: float | None
    band: Literal["none", "weak", "learning", "mastered"]


class HeatmapRow(BaseModel):
    code: str
    title: str
    mastery: float
    band: str
    coverage: float
    weight: float
    cells: list[HeatmapCell]


class ProjectionOut(BaseModel):
    status: Literal["insufficient_history", "on_track", "behind", "done"]
    days_remaining: int
    target_days: int
    goal: float
    coverage: float
    remaining_weighted: float
    topics_remaining: int
    sessions_in_window: int
    coverage_per_day: float | None
    minutes_per_day: float | None
    projected_coverage: float | None
    needed_minutes_per_day: float | None
    needed_hours_per_day: float | None


class CalibrationLevel(BaseModel):
    level: int
    label: str
    stated: float
    answers: int
    accuracy: float | None


class CalibrationOut(BaseModel):
    rated: int
    bias: float | None
    verdict: Literal["insufficient", "overconfident", "underconfident", "calibrated"]
    levels: list[CalibrationLevel]
    wrong: int
    confident_wrong: int
    confident_wrong_share: float | None
    min_rated: int


class InsightsOut(BaseModel):
    heatmap: list[HeatmapRow]
    projection: ProjectionOut
    calibration: CalibrationOut
    weight_policy: str
    notice: str
