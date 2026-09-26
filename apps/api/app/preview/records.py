"""Record types held by the non-release preview state (ADR 0006)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PreviewSource:
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    title: str
    kind: str
    content: str
    status: str
    page_count: int
    figure_count: int
    chunk_count: int
    object_key: str
    created_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PreviewPage:
    id: UUID
    tenant_id: UUID
    source_id: UUID
    page_no: int
    width: int
    height: int
    image_key: str
    has_text_layer: bool


@dataclass(frozen=True, slots=True)
class PreviewBlock:
    id: UUID
    tenant_id: UUID
    source_id: UUID
    page_id: UUID
    page_no: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float]
    heading_path: tuple[str, ...]
    order: int


@dataclass(frozen=True, slots=True)
class PreviewFigure:
    id: UUID
    tenant_id: UUID
    source_id: UUID
    block_id: UUID
    page_no: int
    image_key: str
    caption: str
    modality: str


@dataclass(frozen=True, slots=True)
class PreviewChunk:
    id: UUID
    tenant_id: UUID
    source_id: UUID
    page_no: int
    block_start: UUID
    block_end: UUID
    text: str
    heading_path: tuple[str, ...]
    chunk_hash: str


@dataclass
class PreviewStep:
    name: str
    status: str = "pending"
    attempts: int = 0
    error_code: str | None = None


@dataclass
class PreviewJob:
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    source_id: UUID
    status: str
    idempotency_key: str
    steps: dict[str, PreviewStep]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PreviewClaim:
    id: UUID
    tenant_id: UUID
    source_id: UUID
    text: str
    citation: dict[str, object]
    verification: str = "extracted"


@dataclass
class PreviewCard:
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    prompt: str
    answer: str
    citation: dict[str, object]
    due_at: datetime
    stability: float = 1.0
    difficulty: float = 5.0
    reps: int = 0
    lapses: int = 0


@dataclass(frozen=True, slots=True)
class PreviewQuestion:
    id: UUID
    tenant_id: UUID
    curriculum_code: str
    stem: str
    options: tuple[str, ...]
    key: int
    explanation: str
    citation: dict[str, object]


@dataclass
class PreviewAttempt:
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    question_id: UUID
    selected_option: int | None
    correct: bool
    created_at: datetime


@dataclass
class PreviewExam:
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    question_ids: tuple[UUID, ...]
    answers: dict[UUID, int] = field(default_factory=dict)
    status: str = "created"
    revision: int = 0
    started_at: datetime | None = None
    deadline_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PreviewAudit:
    tenant_id: UUID
    actor_id: UUID
    action: str
    target_type: str
    target_id: str
    created_at: datetime
