"""Pydantic output schemas for the viva examiner and staged image-case agents.

The JSON Schemas handed to the model are generated from these models with
``inline_schema`` and checked in under ``packages/prompts/schemas`` (hard rule
2). Citations are excerpt ids exactly as supplied in the prompt (``E1``..,
``F1``); code resolves them to source/page/block provenance and drops any id
that was not supplied, failing closed when nothing cited survives.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.assessment.models import SchemeItem

Stage = Literal["describe", "findings", "diagnosis", "differentials", "next_step"]


class ExpectedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: str = Field(description="One point a passing candidate states, from the excerpts.")
    citations: list[str] = Field(min_length=1, description="Excerpt ids supporting the point.")


class ExaminerQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="One examiner question; no leading, no praise.")
    hint: str = Field(description="Probe only: a non-leading nudge; '' when escalating.")
    expected_points: list[ExpectedPoint] = Field(min_length=1, max_length=6)


class VivaOpening(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(description="Specific radiology topic of the case, most specific form.")
    scenario: str = Field(description="Case or image scenario read to the candidate.")
    citations: list[str] = Field(min_length=1, description="Excerpt ids behind the scenario.")
    question: ExaminerQuestion


class PointCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, description="0-based index into the current expected points.")
    status: Literal["matched", "partial", "missed"]
    justification: str = Field(description="What in the answer earned or missed the point.")


class TeachingPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The discriminating fact the candidate should remember.")
    citations: list[str] = Field(min_length=1)


class VivaTurnGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[PointCheck]
    reasoning: int = Field(ge=0, le=4, description="Differential and reasoning quality, 0-4.")
    communication: int = Field(ge=0, le=4, description="Structure and clarity, 0-4.")
    unsafe: bool = Field(description="True when the answer states something dangerous.")
    feedback: str = Field(description="Two sentences on what was missed; no praise inflation.")
    teaching_point: TeachingPoint
    escalate: ExaminerQuestion = Field(description="Next question one level deeper.")
    probe: ExaminerQuestion = Field(description="Re-approach of the weak point with a hint.")


class StageRubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Stage
    model_answer: str = Field(description="What a passing candidate says at this stage.")
    points: list[SchemeItem] = Field(min_length=1, max_length=8)


class StagedCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    stem: str = Field(description="Station text shown with the image; never the diagnosis.")
    citations: list[str] = Field(min_length=1)
    stages: list[StageRubric] = Field(description="Exactly five, in the fixed stage order.")
