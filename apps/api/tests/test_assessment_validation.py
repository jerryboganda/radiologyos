"""Deterministic item checks, citation resolution, and agent contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from evals.contracts import load_eval_fixtures
from packages.assessment.models import GeneratedItem, GeneratedQuestions, QuestionCheck, SeqGrade
from packages.assessment.validation import (
    Excerpt,
    check_item,
    render_excerpts,
    resolve,
    stored_parts,
)
from packages.library.parse_models import inline_schema
from packages.models.gateway import load_agent

ROOT = Path(__file__).resolve().parents[3]
FIGURE = uuid4()
EXCERPTS = [
    Excerpt("F1", "Fig 1", "Axial HRCT: crazy paving", {"kind": "figure", "page_no": 3},
            figure_id=FIGURE),
    Excerpt("E1", "PAP", "Crazy paving in PAP", {"kind": "chunk", "page_from": 2}),
    Excerpt("E2", "DDx", "Oedema, PCP, ARDS", {"kind": "chunk", "page_from": 4}),
]
SUPPLIED = [e.ref for e in EXCERPTS]


def sba_item(**overrides: Any) -> GeneratedItem:
    options = [{"text": t, "explanation": f"because {t}", "citations": ["E1"]}
               for t in ("Pulmonary alveolar proteinosis", "Pulmonary oedema",
                         "Pneumocystis pneumonia", "ARDS", "Sarcoidosis")]
    values: dict[str, Any] = {
        "type": "sba", "topic": "PAP", "stem": "A 40-year-old has geographic HRCT change. "
        "Most likely diagnosis?", "options": options, "key_index": 0, "model_answer": "",
        "marking_scheme": [], "key_findings": [], "viva_turns": [], "explanation": "x",
        "citations": ["E1"], "difficulty": 3, "cognitive_level": "application",
    }
    return GeneratedItem.model_validate({**values, **overrides})


def seq_item(item_type: str = "seq", **overrides: Any) -> GeneratedItem:
    values: dict[str, Any] = {
        "type": item_type, "topic": "PAP", "stem": "Discuss crazy paving.", "options": [],
        "key_index": -1, "model_answer": "PAP", "key_findings": ["crazy paving"],
        "marking_scheme": [{"point": "PAP", "marks": 5, "citations": ["E1"]}],
        "viva_turns": [], "explanation": "x", "citations": ["E1"], "difficulty": 2,
        "cognitive_level": "recall",
    }
    return GeneratedItem.model_validate({**values, **overrides})


def test_well_formed_sba_passes() -> None:
    assert check_item(sba_item(), "sba", SUPPLIED) == []


def test_citation_to_unsupplied_excerpt_is_rejected() -> None:
    assert "citation_not_supplied" in check_item(sba_item(citations=["E9"]), "sba", SUPPLIED)
    options = sba_item().model_dump()["options"]
    options[3]["citations"] = ["E7"]
    assert "citation_not_supplied" in check_item(sba_item(options=options), "sba", SUPPLIED)


@pytest.mark.parametrize(("change", "problem"), [
    ({"options": sba_item().model_dump()["options"][:4]}, "sba_requires_five_options"),
    ({"key_index": -1}, "sba_key_out_of_range"),
    ({"stem": "Pulmonary alveolar proteinosis shows what?"}, "sba_key_repeated_in_stem"),
    ({"stem": "word " * 121}, "sba_stem_too_long"),
    ({"type": "seq"}, "type_mismatch"),
])
def test_sba_deterministic_failures(change: dict[str, Any], problem: str) -> None:
    assert problem in check_item(sba_item(**change), "sba", SUPPLIED)


def test_banned_and_duplicate_options() -> None:
    options = sba_item().model_dump()["options"]
    options[4]["text"] = "All of the above"
    assert "sba_all_or_none_of_the_above" in check_item(sba_item(options=options), "sba",
                                                        SUPPLIED)
    options[4]["text"] = options[0]["text"].upper()
    assert "sba_options_not_distinct" in check_item(sba_item(options=options), "sba", SUPPLIED)


def test_free_text_item_requirements() -> None:
    assert check_item(seq_item(), "seq", SUPPLIED) == []
    assert "marking_scheme_missing" in check_item(seq_item(marking_scheme=[]), "seq", SUPPLIED)
    assert "image_case_findings_missing" in check_item(
        seq_item("image_case", key_findings=[]), "image_case", SUPPLIED)
    turns = [{"question": "q", "expected_answer": "a", "citations": ["E1"]}]
    assert "viva_chain_too_short" in check_item(seq_item("viva", viva_turns=turns), "viva",
                                                SUPPLIED)


def test_stored_parts_resolve_provenance_and_figure() -> None:
    parts = stored_parts(seq_item("image_case", citations=["F1", "E1"]), EXCERPTS)
    assert parts["figure_id"] == FIGURE
    assert [c["ref"] for c in parts["citations"]] == ["F1", "E1"]
    assert parts["citations"][0]["page_no"] == 3
    assert parts["answer"]["marking_scheme"][0]["citations"][0]["page_from"] == 2
    sba = stored_parts(sba_item(), EXCERPTS)
    assert sba["answer"] == {"key": 0} and sba["figure_id"] is None
    with pytest.raises(KeyError):
        resolve(["E5"], EXCERPTS)


def test_excerpts_render_as_tagged_data() -> None:
    rendered = render_excerpts(EXCERPTS)
    assert rendered.count("<excerpt id=") == 3 and '<excerpt id="E2">' in rendered


@pytest.mark.parametrize(("agent", "model", "route"), [
    ("question_generate", GeneratedQuestions, "reason"),
    ("question_check", QuestionCheck, "classify"),
    ("seq_grade", SeqGrade, "reason"),
])
def test_agents_are_versioned_with_generated_schemas(agent: str, model: Any, route: str) -> None:
    loaded = load_agent(agent, 1)
    assert loaded.output_model is model
    assert loaded.schema == inline_schema(model)
    assert (loaded.prompt.route.value, loaded.prompt.effort) == (route, "high")
    assert loaded.prompt.fixture == "evals/fixtures/assessment_v1.json"
    fixture = load_eval_fixtures(ROOT / loaded.prompt.fixture)
    assert any(case.prompt == f"{agent}/v1.yaml" for case in fixture.cases)
    stored = json.loads((ROOT / "packages/prompts" / loaded.prompt.output_schema).read_text())
    assert stored == inline_schema(model)


def test_checker_pass_requires_every_check() -> None:
    ok = {"single_best_answer": True, "key_supported": True, "no_cueing": True,
          "distractors_plausible": True, "difficulty_agrees": False, "verdict": "pass",
          "reasons": []}
    assert QuestionCheck.model_validate(ok).passed
    assert not QuestionCheck.model_validate({**ok, "key_supported": False}).passed
    assert not QuestionCheck.model_validate({**ok, "verdict": "fail"}).passed
