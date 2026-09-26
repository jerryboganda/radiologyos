"""Output schemas for the knowledge-depth agents (ADR 0030, hard rule 2).

* ``concept_synthesis`` (route ``extract``): a canonical concept note whose every
  sentence cites claim labels (``C1``...) exactly as supplied in the prompt;
* ``concept_resolver`` (route ``reason``): merge / distinct / parent-child for a
  concept pair in the 0.80-0.92 similarity band;
* ``claim_conflict`` (route ``reason``): true conflict / different context /
  same fact for a claim pair, with a rationale that cites ``A`` and/or ``B``.

The JSON Schemas under ``packages/prompts/schemas`` are generated from these
models with ``inline_schema``; citations are checked again in code because the
schema cannot prove a label was supplied or that a sentence is supported.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimRef = str


class NoteSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=600, description="One sentence, no new facts.")
    cites: list[ClaimRef] = Field(
        min_length=1, max_length=6,
        description="Claim labels exactly as supplied (e.g. 'C3') that support the sentence.",
    )


class ModalityFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modality: str = Field(min_length=1, max_length=40, description="e.g. CT, MRI, US, X-ray.")
    sentences: list[NoteSentence] = Field(max_length=8)


class DifferentialItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="Differential diagnosis name.")
    discriminators: list[NoteSentence] = Field(
        max_length=4, description="Cited features that tell it apart from the concept."
    )


class ConceptNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: list[NoteSentence] = Field(max_length=4)
    imaging: list[ModalityFeatures] = Field(max_length=6)
    differentials: list[DifferentialItem] = Field(max_length=8)
    pearls: list[NoteSentence] = Field(max_length=6)
    pitfalls: list[NoteSentence] = Field(max_length=6)


class ResolverDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["merge", "distinct", "parent_child"]
    parent: Literal["A", "B", ""] = Field(
        description="For parent_child, which concept is the broader one; '' otherwise."
    )
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=1000)


class ConflictVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["conflict", "context", "same"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(
        min_length=1, max_length=1000,
        description="Why, referring to the statements as [A] and [B].",
    )
    cites: list[Literal["A", "B"]] = Field(
        min_length=1, max_length=2, description="Which statements the rationale relies on."
    )
    context: str = Field(
        max_length=300,
        description="For 'context': the condition under which each holds; '' otherwise.",
    )
