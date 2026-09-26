"""Pydantic output schemas for the assessment agents (hard rule 2).

The JSON Schema handed to the model is generated from these models with
``inline_schema`` and checked in under ``packages/prompts/schemas``; every model
output is validated against them before anything is stored or shown.

Citations are excerpt ids exactly as supplied in the prompt (``E1``, ``E2``,
``F1``); code maps them back to source/page/block provenance and rejects any
id that was not supplied.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemType = Literal["sba", "seq", "image_case", "viva"]
ExcerptIds = list[str]


class SbaOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="Option text, short and homogeneous with its siblings.")
    explanation: str = Field(description="Why this option is right or wrong, from the excerpts.")
    citations: ExcerptIds = Field(description="Excerpt ids supporting the explanation.")


class SchemeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: str = Field(description="One markable point an examiner would credit.")
    marks: float = Field(gt=0, le=10)
    citations: ExcerptIds = Field(min_length=1)


class VivaTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="Examiner question; each turn probes one level deeper.")
    expected_answer: str
    citations: ExcerptIds = Field(min_length=1)


class GeneratedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ItemType
    topic: str = Field(description="Specific radiology topic, most specific form.")
    stem: str = Field(description="Clinical/imaging stem or scenario.")
    options: list[SbaOption] = Field(description="SBA only: exactly 5 options; [] otherwise.")
    key_index: int = Field(ge=-1, le=4, description="SBA: 0-based best answer; -1 otherwise.")
    model_answer: str = Field(description="SEQ, image case, viva: model answer; '' for SBA.")
    marking_scheme: list[SchemeItem] = Field(
        description="SEQ, image case, viva: weighted, cited points; [] for SBA."
    )
    key_findings: list[str] = Field(description="Image case: findings expected; [] otherwise.")
    viva_turns: list[VivaTurn] = Field(description="Viva: escalating question chain; [] otherwise.")
    explanation: str = Field(description="Teaching explanation of the key/model answer.")
    citations: ExcerptIds = Field(min_length=1, description="Excerpt ids supporting the key.")
    difficulty: int = Field(ge=1, le=5)
    cognitive_level: Literal["recall", "application", "analysis"]


class GeneratedQuestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GeneratedItem]


class QuestionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    single_best_answer: bool = Field(
        description="SBA: exactly one option is defensibly best. True for other types."
    )
    key_supported: bool = Field(
        description="The key or every marking-scheme point is entailed by its cited excerpt."
    )
    no_cueing: bool = Field(description="No grammatical, length, or wording cue to the key.")
    distractors_plausible: bool = Field(
        description="SBA: every distractor is plausible yet wrong. True for other types."
    )
    difficulty_agrees: bool
    verdict: Literal["pass", "fail"]
    reasons: list[str] = Field(description="One short reason per failed check; [] on pass.")

    @property
    def passed(self) -> bool:
        return self.verdict == "pass" and all(
            (self.single_best_answer, self.key_supported, self.no_cueing,
             self.distractors_plausible)
        )


class PointGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_index: int = Field(ge=0, description="0-based index into the frozen marking scheme.")
    status: Literal["matched", "partial", "missed"]
    awarded: float = Field(ge=0, description="Marks awarded, never above the point's marks.")
    justification: str = Field(description="What in the answer earned or missed the point.")


class SeqGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[PointGrade]
    feedback: str = Field(description="Short, specific feedback tied to missed scheme points.")
