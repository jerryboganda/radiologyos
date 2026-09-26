"""Pydantic output schemas for the knowledge agents (hard rule 2).

The JSON Schema handed to the model is generated from these models with
``inline_schema`` and every output is validated against them before storage.
Evidence spans are additionally checked in code (``evidence.verify_span``):
the schema cannot prove that a span is a verbatim substring of the chunk.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConceptType = Literal[
    "disease", "finding", "sign", "anatomy", "technique", "modality",
    "classification", "physics", "drug", "other",
]
ClaimType = Literal[
    "definition", "imaging_finding", "epidemiology", "pathology", "clinical",
    "differential", "classification", "management", "physics", "other",
]
Relation = Literal[
    "is_a", "part_of", "differential_of", "sign_of", "causes", "seen_on",
    "contrasts_with", "classified_by", "associated_with",
]
ExamTarget = Literal["imm", "fcps2_theory", "fcps2_toacs", "frcr", "unknown"]
EXAM_TARGETS: tuple[str, ...] = ("imm", "fcps2_theory", "fcps2_toacs", "frcr", "unknown")


class ExtractedConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="Canonical concept name.")
    type: ConceptType
    aliases: list[str] = Field(
        max_length=10, description="Abbreviations, eponyms, spelling variants seen in the text."
    )


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str = Field(min_length=1, max_length=200, description="Name from concepts.")
    type: ClaimType
    text: str = Field(min_length=1, max_length=1000, description="One atomic statement.")
    evidence_span: str = Field(
        min_length=1, max_length=1000,
        description="Exact, verbatim substring of the chunk that supports the claim.",
    )
    importance: int = Field(ge=1, le=5, description="5 = high-yield exam fact.")
    modality: str = Field(max_length=40, description="Imaging modality, or '' if none.")


class ExtractedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: str = Field(min_length=1, max_length=200)
    dst: str = Field(min_length=1, max_length=200)
    relation: Relation


class KnowledgeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concepts: list[ExtractedConcept] = Field(max_length=30)
    claims: list[ExtractedClaim] = Field(max_length=40)
    relations: list[ExtractedRelation] = Field(max_length=30)


class TopicMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curriculum_code: str = Field(
        min_length=1, max_length=60, description="One code from the supplied curriculum list."
    )
    topic: str = Field(max_length=200, description="Specific topic, e.g. 'pulmonary embolism'.")
    confidence: float = Field(ge=0, le=1)


class TopicClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[TopicMapping] = Field(max_length=5, description="Most confident first.")


class PaperQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_no: str = Field(max_length=20, description="Question number as printed, or ''.")
    curriculum_code: str = Field(min_length=1, max_length=60)
    topic: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)


class PaperTopics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_exam_paper: bool = Field(description="True only if the page shows exam questions.")
    exam_target: ExamTarget
    year: int | None = Field(ge=1990, le=2100, description="Sitting year if printed, else null.")
    paper_label: str = Field(max_length=120, description="Paper/sitting label if printed, or ''.")
    questions: list[PaperQuestion] = Field(max_length=60)
