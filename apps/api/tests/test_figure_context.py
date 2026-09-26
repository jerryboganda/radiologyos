"""Figure diagnoses are anchored to the owner's pages, never invented as fact (ADR 0036)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.library.figure_context import (
    build_context,
    case_text,
    evidence_description,
    impression_origin,
    neighbour_pages,
    quote_in_context,
)
from packages.library.parse_models import SourceImageCase, inline_schema
from packages.models.gateway import load_agent, user_prompt

ROOT = Path(__file__).resolve().parents[3]


def _case(**extra: Any) -> SourceImageCase:
    base: dict[str, Any] = {
        "modality": "Radiograph", "anatomy": "abdomen", "visible_text": "", "findings": ["x"],
        "impression": "Horseshoe kidney", "differentials": ["Crossed ectopia"],
        "teaching_points": [], "topics": ["renal anomalies"], "confidence": "high",
        "impression_source": "source", "source_quote": "Diagnosis: horseshoe kidney"}
    return SourceImageCase(**{**base, **extra})


def test_context_is_this_page_then_the_answer_page_after_it() -> None:
    context = build_context(5, {5: "Q1. What is the diagnosis?", 6: "Diagnosis: horseshoe kidney"})
    assert context.splitlines() == ["[this page] Q1. What is the diagnosis?",
                                    "[page 6] Diagnosis: horseshoe kidney"]
    assert build_context(5, {5: "", 6: "x"}) == "[page 6] x"  # an empty page is left out
    assert build_context(1, {}) == "(no text on this page or its neighbours)"
    # Never the page before or two on: those hold other cases' answers.
    assert neighbour_pages(1) == (1, 2) and neighbour_pages(10) == (10, 11)


def test_quote_must_really_be_in_the_page_text() -> None:
    context = "[page 6] DIAGNOSIS:  Horseshoe kidney – fused lower poles"
    assert quote_in_context("Diagnosis: horseshoe kidney", context)
    assert not quote_in_context("horseshoe kidneys", context)  # no partial words
    assert not quote_in_context("What is the diagnosis?", "What is the diagnosis?")
    assert not quote_in_context("", context)


def test_only_a_verified_quote_makes_an_impression_the_sources() -> None:
    context = "[page 6] Diagnosis: horseshoe kidney"
    assert impression_origin(_case(), context) == ("source", "Diagnosis: horseshoe kidney")
    assert impression_origin(_case(source_quote="Diagnosis: Wilms tumour"), context) \
        == ("model", None)
    assert impression_origin(_case(impression_source="model"), context) == ("model", None)


def test_unverified_impressions_are_labelled_and_never_cited() -> None:
    text = case_text(_case(), "model")
    assert "Impression (unverified model opinion): Horseshoe kidney" in text
    cited = evidence_description(text)
    assert "Horseshoe kidney" not in cited and "Differentials" in cited
    sourced = case_text(_case(), "source")
    assert evidence_description(sourced) == sourced
    assert "Impression (stated in the source): Horseshoe kidney" in sourced


def test_v2_prompt_carries_the_context_and_its_generated_schema() -> None:
    agent = load_agent("image_case", 2)
    assert agent.output_model is SourceImageCase and agent.schema == inline_schema(SourceImageCase)
    stored = json.loads((ROOT / "packages/prompts" / agent.prompt.output_schema).read_text())
    assert stored == inline_schema(SourceImageCase)
    prompt = user_prompt("image_case", 2, figure_no="1", page_no="5", caption="c",
                         context="[page 6] Diagnosis: X")
    assert "[page 6] Diagnosis: X" in prompt
    assert load_agent("image_case", 1).output_model is not SourceImageCase  # tutor stays on v1
