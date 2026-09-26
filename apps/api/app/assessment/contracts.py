"""Request/response contracts for the assessment API, and the key-hiding views.

``public_question`` is the only way a question leaves the API before it has
been answered: it carries the stem, option texts, and figure link, never the
key, model answer, marking scheme, explanations, or checker reasons. Keys,
explanations, and citations are revealed only in an attempt result or in a
submitted exam's result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ItemType = Literal["sba", "seq", "image_case", "viva"]
ExamTarget = Literal["fcps2_theory", "fcps2_toacs", "imm", "frcr"]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[UUID] = Field(default_factory=list, max_length=20)
    topic: str | None = Field(default=None, min_length=2, max_length=200)
    type: ItemType
    exam_target: ExamTarget
    count: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def require_scope(self) -> GenerateRequest:
        if not self.topic and not self.source_ids:
            raise ValueError("give a topic, source_ids, or both")
        return self


class QuestionPublic(BaseModel):
    id: UUID
    type: str
    exam_tags: list[str]
    topic: str
    stem: str
    options: list[str]
    figure_id: UUID | None
    figure_image_path: str | None
    status: str
    checked: bool
    difficulty: int | None
    created_at: datetime


class RejectedItem(BaseModel):
    index: int
    reasons: list[str]


class GenerateResponse(BaseModel):
    created: list[QuestionPublic]
    rejected: list[RejectedItem]
    excerpt_count: int


class AttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_option: int | None = Field(default=None, ge=0, le=4)
    answer_text: str | None = Field(default=None, min_length=1, max_length=8000)


class AttemptResponse(BaseModel):
    attempt_id: UUID | None
    question_id: UUID
    type: str
    score: float
    max_score: float
    correct: bool | None = None
    key: int | None = None
    explanation: str
    option_explanations: list[dict[str, Any]] = Field(default_factory=list)
    points: list[dict[str, Any]] = Field(default_factory=list)
    feedback: str = ""
    model_answer: str = ""
    key_findings: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]]


class ExamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["practice", "exam"] = "exam"
    exam_target: ExamTarget | None = None
    topic: str | None = Field(default=None, min_length=2, max_length=200)
    count: int = Field(default=20, ge=1, le=200)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=300)

    @model_validator(mode="after")
    def require_limit_for_exam(self) -> ExamCreate:
        if self.mode == "exam" and self.time_limit_minutes is None:
            raise ValueError("exam mode requires time_limit_minutes")
        return self


class AutosaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    answers: dict[str, int | None] = Field(max_length=300)


class AutosaveResponse(BaseModel):
    exam_id: UUID
    revision: int
    deadline_at: datetime | None
    answers: dict[str, int]


class ExamSummary(BaseModel):
    id: UUID
    mode: str
    status: str
    started_at: datetime
    deadline_at: datetime | None
    submitted_at: datetime | None
    question_count: int
    answered: int
    score_percent: float | None


class ExamView(BaseModel):
    id: UUID
    mode: str
    status: str
    config: dict[str, Any]
    started_at: datetime
    deadline_at: datetime | None
    submitted_at: datetime | None
    server_time: datetime
    revision: int
    answers: dict[str, int]
    questions: list[QuestionPublic]
    result: dict[str, Any] | None


def public_question(row: dict[str, Any]) -> QuestionPublic:
    quality = row.get("quality") or {}
    figure_id = row.get("figure_id")
    return QuestionPublic(
        id=row["id"], type=row["type"], exam_tags=list(row["exam_tags"] or []),
        topic=row["topic"], stem=row["stem"],
        options=[option["text"] for option in row["options"]],
        figure_id=figure_id,
        figure_image_path=f"/v1/library/figures/{figure_id}/image" if figure_id else None,
        status=row["status"], checked=bool(quality.get("passed")),
        difficulty=quality.get("difficulty"), created_at=row["created_at"],
    )
