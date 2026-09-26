"""Contracts for the draft review queue and item statistics.

A review item is the owner's own draft shown in full (key, scheme, and
citations) so it can be judged; drafts are never placed in an exam, and an
approved item keeps its original citations because citations are not editable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from packages.assessment.review import checker_reasons
from pydantic import BaseModel, ConfigDict, Field, model_validator

_EDIT_FIELDS = ("stem", "topic", "explanation", "options", "key_index", "model_answer")


class ReviewItem(BaseModel):
    id: UUID
    type: str
    exam_tags: list[str]
    topic: str
    stem: str
    options: list[dict[str, Any]]
    key: int | None
    model_answer: str
    marking_scheme: list[dict[str, Any]]
    key_findings: list[str]
    viva_turns: list[dict[str, Any]]
    explanation: str
    citations: list[dict[str, Any]]
    figure_image_path: str | None
    status: str
    status_reason: str | None
    checker_reasons: list[str]
    difficulty: int | None
    created_at: datetime


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject", "edit"]
    stem: str | None = Field(default=None, min_length=1, max_length=8000)
    topic: str | None = Field(default=None, min_length=1, max_length=300)
    explanation: str | None = Field(default=None, max_length=8000)
    options: list[str] | None = Field(default=None, min_length=5, max_length=5)
    key_index: int | None = Field(default=None, ge=0, le=4)
    model_answer: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode="after")
    def fields_only_on_edit(self) -> ReviewRequest:
        given = [f for f in _EDIT_FIELDS if getattr(self, f) is not None]
        if self.action == "edit" and not given:
            raise ValueError("edit needs at least one field")
        if self.action != "edit" and given:
            raise ValueError("fields are accepted only with action=edit")
        return self

    def edits(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in _EDIT_FIELDS if getattr(self, f) is not None}


class ReviewResponse(BaseModel):
    action: str
    status: str
    item: ReviewItem


class ItemStatOut(BaseModel):
    question_id: UUID
    attempts: int
    correct: int
    p_value: float | None
    discrimination: float | None
    discrimination_n: int
    decision: str
    reason: str | None


class RetiredOut(BaseModel):
    question_id: UUID
    reason: str


class StatsRecomputeResponse(BaseModel):
    computed: int
    retired: list[RetiredOut]
    stats: list[ItemStatOut]


def review_item(row: dict[str, Any]) -> ReviewItem:
    answer = row["answer"] or {}
    quality = row.get("quality") or {}
    figure_id = row.get("figure_id")
    return ReviewItem(
        id=row["id"], type=row["type"], exam_tags=list(row["exam_tags"] or []),
        topic=row["topic"], stem=row["stem"], options=list(row["options"] or []),
        key=answer.get("key"), model_answer=answer.get("model_answer", ""),
        marking_scheme=answer.get("marking_scheme", []),
        key_findings=answer.get("key_findings", []), viva_turns=answer.get("viva_turns", []),
        explanation=row["explanation"], citations=row["citations"],
        figure_image_path=f"/v1/library/figures/{figure_id}/image" if figure_id else None,
        status=row["status"], status_reason=row.get("status_reason"),
        checker_reasons=checker_reasons(quality), difficulty=quality.get("difficulty"),
        created_at=row["created_at"],
    )
