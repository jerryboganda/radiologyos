from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from apps.api.app.schemas.common import Citation
from pydantic import BaseModel, ConfigDict, Field


class PreviewSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    kind: Literal["pdf", "docx", "pptx", "image", "note"]
    content: str = Field(min_length=1, max_length=200_000)


class PreviewSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    id: str
    title: str
    kind: str
    status: str
    page_count: int
    figure_count: int
    chunk_count: int
    created_at: datetime


class PreviewStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: str
    attempts: int
    error_code: str | None = None


class PreviewJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    id: str
    source_id: str
    status: str
    steps: tuple[PreviewStepResponse, ...]


class PreviewBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    page_no: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float]
    heading_path: tuple[str, ...]


class PreviewFigureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    page_no: int
    caption: str
    modality: str
    image_key: str


class PreviewPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    page_no: int
    width: int
    height: int
    image_key: str
    blocks: tuple[PreviewBlockResponse, ...]
    figures: tuple[PreviewFigureResponse, ...]


class PreviewSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


class PreviewSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    score: float
    citation: Citation


class PreviewSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    query: str
    chunks: tuple[PreviewSearchHit, ...]
    figures: tuple[PreviewFigureResponse, ...]


class PreviewDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    status: Literal["deleted"]
    source_id: str


class PreviewConceptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    type: str
    status: str
    claim_ids: tuple[str, ...]


class PreviewClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    verification: str
    citation: Citation


class PreviewConflictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: str
    description: str
    claim_ids: tuple[str, ...]


class PreviewTutorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1_000)


class PreviewTutorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    answer: str
    citations: tuple[Citation, ...]
    figures: tuple[PreviewFigureResponse, ...]
    grounding: Literal["mock_lexical_preview"]


class PreviewOnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_date: date
    hours_per_week: int = Field(ge=1, le=40)
    session_minutes: Literal[30, 60, 90]


class PreviewPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    plan_id: str
    plan_version: int
    exam_date: str
    timezone: str
    hours_per_week: int
    session_minutes: int
    days_remaining: int
    phase: str
    priority: tuple[dict[str, object], ...]
    baseline_status: str
    weight_policy: str
    notice: str


class PreviewTodayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    session_id: str
    plan_version: int
    days_remaining: int
    phase: str
    blocks: tuple[dict[str, object], ...]
    omitted_blocks: tuple[str, ...]


class PreviewCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    prompt: str
    citation: Citation
    due_at: datetime


class PreviewReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal[1, 2, 3, 4]


class PreviewMasteryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    version: int
    method: str
    nodes: tuple[dict[str, object], ...]


class PreviewQuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    kind: Literal["sba"]
    stem: str
    options: tuple[str, ...]
    curriculum_code: str
    citations: tuple[Citation, ...]


class PreviewPracticeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    questions: tuple[PreviewQuestionResponse, ...]


class PreviewAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    selected_option: int = Field(ge=0, le=4)
    confidence: int | None = Field(default=None, ge=1, le=5)


class PreviewAttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    attempt_id: str
    grade: dict[str, object]
    mastery: PreviewMasteryResponse


class PreviewExamResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    exam_id: str
    status: str
    revision: int
    time_limit_s: Literal[600] = 600
    questions: tuple[PreviewQuestionResponse, ...]
    saved_answers: dict[str, int]
    deadline_at: datetime | None = None


class PreviewAutosaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    answers: dict[str, int]


class PreviewExamResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    exam_id: str
    status: str
    score: float
    max_score: float
    breakdown: tuple[dict[str, object], ...]
    submitted_at: datetime


class PreviewBillingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    provider: Literal["mock_stripe_test_mode"]
    status: str
    message: str


class PreviewMarkdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    filename: str
    markdown: str


class PreviewReleaseAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    status: Literal["blocked"]
    completed: tuple[str, ...]
    blocked: tuple[str, ...]


class PreviewCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slice: str
    status: Literal["preview", "blocked"]
    note: str


class PreviewCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    capabilities: tuple[PreviewCapabilityResponse, ...]


class PreviewQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    conflicts: tuple[PreviewConflictResponse, ...]
    pending_mappings: int
    pending_questions: int


class PreviewConflictResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["accept_a", "accept_b", "keep_both"]


class PreviewAdminResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview"] = "preview"
    role: str
    source_count: int
    open_conflicts: int
    billing_status: str
