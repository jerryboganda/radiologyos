"""Validated output of the ``card_generate`` agent (packages/prompts/card_generate)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GeneratedCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID = Field(description="Id of the supplied chunk that supports this card.")
    curriculum_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]*$", max_length=64)
    topic: str = Field(min_length=1, max_length=200)
    front: str = Field(min_length=1, max_length=2000)
    back: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(
        min_length=1, max_length=1000,
        description="A verbatim span of the cited chunk that supports the back.",
    )


class CardBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[GeneratedCard] = Field(max_length=20)
