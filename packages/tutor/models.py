"""Pydantic schemas for the grounded tutor (hard rules 2 and 3).

Two groups live here:

* agent outputs (``SourceAnswer`` for ``tutor_answer``, ``WebAnswer`` for
  ``tutor_web``) — the JSON Schema passed to the model is generated from them
  and every output is validated against them before use;
* the grounded result (``GroundedAnswer``) that code builds after checking
  every citation. Model citations are never trusted as-is: a source label must
  name an excerpt that was actually retrieved for this question, and a web URL
  must be an https link on an allow-listed authoritative domain.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Grounding = Literal["sources", "web", "mixed", "none"]
Origin = Literal["sources", "web"]


class SourceSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1, max_length=2000,
        description="One or two sentences of the answer, supported by the cited excerpts.",
    )
    sources: list[str] = Field(
        max_length=8,
        description='Excerpt labels that support this text, e.g. ["S1", "S3"]. Never empty.',
    )


class SourceAnswer(BaseModel):
    """Output of ``tutor_answer``: an answer drawn only from numbered excerpts."""

    model_config = ConfigDict(extra="forbid")

    segments: list[SourceSegment] = Field(
        max_length=40, description="The answer in reading order; [] if nothing is covered."
    )
    coverage: Literal["full", "partial", "none"] = Field(
        description="How completely the excerpts answer the question."
    )


class WebSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1, max_length=2000,
        description="One or two sentences of the answer, supported by the cited pages.",
    )
    urls: list[str] = Field(
        max_length=5,
        description="https URLs of the authoritative pages actually read. Never empty.",
    )


class WebAnswer(BaseModel):
    """Output of ``tutor_web``: an answer researched on authoritative sites."""

    model_config = ConfigDict(extra="forbid")

    segments: list[WebSegment] = Field(
        max_length=40, description="The answer in reading order; [] if nothing reliable found."
    )


class Citation(BaseModel):
    """A verified citation: an excerpt the retriever returned, or an allowed URL."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "web"]
    label: str | None = None
    chunk_id: UUID | None = None
    source_id: UUID | None = None
    source_title: str | None = None
    page_from: int | None = None
    page_to: int | None = None
    block_refs: list[dict[str, int]] = Field(default_factory=list)
    url: str | None = None


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    origin: Origin
    citations: list[Citation] = Field(min_length=1)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[Segment]
    grounding: Grounding
    dropped_segments: int = Field(default=0, ge=0)
    notice: str | None = None
    agent_version: str = ""

    @property
    def text(self) -> str:
        if not self.segments:
            return self.notice or ""
        return " ".join(segment.text for segment in self.segments)
