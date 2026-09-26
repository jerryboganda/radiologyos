"""Pydantic schemas for the grounded tutor (hard rules 2 and 3).

Two groups live here:

* agent outputs (``SourceAnswer`` for ``tutor_answer``, ``WebAnswer`` /
  ``WebAnswerWithPages`` for ``tutor_web``, ``JudgeVerdicts`` for
  ``grounding_judge``, ``ThreadMemory`` for ``tutor_memory``) — the JSON Schema
  passed to the model is generated from them and every output is validated
  against them before use;
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
Verdict = Literal["supported", "partial", "unsupported"]
# What the semantic judge concluded about a kept segment. ``None`` means the
# segment was not eligible for judging (a web segment with no page summary).
Support = Literal["supported", "partial", "not_verified"]


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


class WebPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(description="https URL of a page actually read (WebFetch).")
    summary: str = Field(
        max_length=1500,
        description="What the page states that is relevant to the question, in plain prose.",
    )


class WebAnswerWithPages(WebAnswer):
    """Output of ``tutor_web`` v2: the answer plus a summary of every page read."""

    model_config = ConfigDict(extra="forbid")

    pages: list[WebPage] = Field(
        max_length=10, description="One entry per cited page, summarising what it states."
    )


class SegmentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment: int = Field(ge=1, description="The n of the <segment n=...> being judged.")
    verdict: Verdict = Field(
        description="supported: every factual assertion is stated or directly implied by the "
                    "cited evidence; partial: some are, at least one is not; unsupported: "
                    "the main assertion is not supported or is contradicted."
    )
    reason: str = Field(max_length=300, description="Under 25 words: what is (not) supported.")


class JudgeVerdicts(BaseModel):
    """Output of ``grounding_judge``: one verdict per numbered segment."""

    model_config = ConfigDict(extra="forbid")

    verdicts: list[SegmentVerdict] = Field(max_length=80)


class ThreadMemory(BaseModel):
    """Output of ``tutor_memory``: a rolling summary of older turns (context only)."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        max_length=3000,
        description="What the candidate asked and was taught so far, in plain prose; "
                    "no citations, labels, or URLs.",
    )


class JudgeStats(BaseModel):
    """What the semantic grounding judge did for one answer (persisted with it)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "failed", "skipped", "not_run"]
    judged: int = Field(default=0, ge=0)
    supported: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    unsupported: int = Field(default=0, ge=0, description="Dropped as unsupported.")
    not_verified: int = Field(default=0, ge=0)
    web_unjudged: int = Field(default=0, ge=0)
    agent_version: str = ""


class Citation(BaseModel):
    """A verified citation: a retrieved excerpt or figure, or an allowed URL."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "web", "figure"]
    label: str | None = None
    chunk_id: UUID | None = None
    figure_id: UUID | None = None
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
    support: Support | None = None
    support_note: str | None = None


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[Segment]
    grounding: Grounding
    dropped_segments: int = Field(default=0, ge=0)
    notice: str | None = None
    agent_version: str = ""
    judge: JudgeStats | None = None

    @property
    def text(self) -> str:
        if not self.segments:
            return self.notice or ""
        return " ".join(segment.text for segment in self.segments)
