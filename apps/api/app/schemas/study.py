"""Request and response contracts for /v1/study."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ExamTarget = Literal["fcps2_theory", "fcps2_toacs", "imm", "frcr"]


class ReminderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_date: date
    exam_targets: list[ExamTarget] = Field(default_factory=list, max_length=4)
    daily_minutes: int = Field(default=90, ge=15, le=600)
    weekday_minutes: int | None = Field(default=None, ge=0, le=600)
    weekend_minutes: int | None = Field(default=None, ge=0, le=600)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    reminder: ReminderSettings = Field(default_factory=ReminderSettings)


class ProfileOut(BaseModel):
    exam_date: date
    exam_targets: list[str]
    daily_minutes: int
    weekday_minutes: int | None
    weekend_minutes: int | None
    timezone: str
    reminder: ReminderSettings
    days_remaining: int
    phase: str


class PlanTopic(BaseModel):
    code: str
    title: str
    minutes: int
    slots: int


class PlanBlock(BaseModel):
    kind: Literal["review", "learn", "test", "viva"]
    minutes: int
    due_cards: int | None = None
    target_cards: int | None = None
    new_cards: int | None = None
    topics: list[PlanTopic] | list[str] | None = None
    questions: int | None = None
    from_today_topics: int | None = None
    interleaved_weak: int | None = None
    weak_topics: list[str] | None = None
    mock_paper_suggested: bool | None = None
    format: str | None = None
    image_prompts: int | None = None


class PriorityItem(BaseModel):
    code: str
    title: str
    priority: float
    mastery: float
    band: str


class PlanOut(BaseModel):
    plan_version: int
    plan_date: date
    exam_date: date
    days_remaining: int
    phase: str
    rule: str
    minutes: int
    retention: float
    exam_targets: list[str]
    weight_policy: str
    blocks: list[PlanBlock]
    priorities: list[PriorityItem]
    generated_at: datetime


class CardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: UUID
    curriculum_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]*$", max_length=64)
    topic: str = Field(min_length=1, max_length=200)
    front: str = Field(min_length=1, max_length=2000)
    back: str = Field(min_length=1, max_length=4000)


class CardCitation(BaseModel):
    source_id: UUID
    source_title: str
    chunk_id: UUID | None = None
    page_from: int
    page_to: int
    block_refs: list[dict[str, int]] = Field(default_factory=list)


class CardOut(BaseModel):
    id: UUID
    curriculum_code: str
    topic: str
    front: str
    back: str
    origin: str
    citation: CardCitation
    state: str
    stability: float
    difficulty: float
    due_at: datetime
    last_review_at: datetime | None
    reps: int
    lapses: int


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=4, description="1 Again, 2 Hard, 3 Good, 4 Easy")


class ReviewOut(BaseModel):
    card: CardOut
    scheduled_days: int
    retention: float


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID | None = None
    chunk_ids: list[UUID] = Field(default_factory=list, max_length=8)
    max_cards: int = Field(default=8, ge=1, le=20)


class GenerateOut(BaseModel):
    created: list[CardOut]
    rejected: int
    chunks_used: int


class TopicProgress(BaseModel):
    code: str
    title: str
    mastery: float
    band: str
    accuracy: float
    retrievability: float
    coverage: float
    cards: int
    lapses: int
    priority: float


class ProgressOut(BaseModel):
    exam_date: date
    days_remaining: int
    phase: str
    retention: float
    cards: int
    due_now: int
    new_cards: int
    reviews_total: int
    reviews_today: int
    topics: list[TopicProgress]
    notice: str
