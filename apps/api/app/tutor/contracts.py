"""Request and response bodies of the tutor API (ADR 0013, ADR 0025, ADR 0028)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from packages.library.parse_models import ImageCase
from packages.tutor.intent import Intent
from packages.tutor.models import Grounding, JudgeStats, Segment
from pydantic import BaseModel, ConfigDict, Field


class Focus(BaseModel):
    """The Reader page a question is about: its excerpts are retrieved first."""

    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    page_no: int = Field(ge=1, le=100_000)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=2000)
    thread_id: UUID | None = None
    allow_web: bool = True
    image_id: UUID | None = Field(
        default=None, description="An image uploaded with POST /v1/tutor/images.")
    focus: Focus | None = None


class AskResponse(BaseModel):
    thread_id: UUID
    message_id: UUID
    grounding: Grounding
    segments: list[Segment]
    notice: str | None
    dropped_segments: int
    agent_version: str
    excerpts_considered: int
    figures_considered: int
    judge: JudgeStats | None
    image_id: UUID | None = None
    image_reading: ImageCase | None = Field(
        default=None, description="AI reading of the attached image; context, never a citation.")
    intent: Intent = Field(default="explain", description="Routed question intent (ADR 0028).")
    quiz_topic: str | None = Field(
        default=None, description="For a quiz request: the topic to generate questions on.")
    graph_claims: int = Field(default=0, description="Knowledge-graph claims (K labels) offered.")
    reranked: bool = Field(default=False, description="Excerpts were reordered by the reranker.")


class ThreadSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ThreadMessage(BaseModel):
    id: UUID
    role: str
    content: str
    grounding: Grounding | None
    segments: list[Segment]
    agent_version: str
    created_at: datetime
    judge: JudgeStats | None = None
    image_id: UUID | None = None
    image_reading: ImageCase | None = None
    intent: Intent | None = None
    quiz_topic: str | None = None


class ThreadDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ThreadMessage]


class ImageUploadResponse(BaseModel):
    image_id: UUID
    content_type: str
    byte_size: int
    width: int
    height: int
