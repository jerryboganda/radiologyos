"""User-turn templates moved into versioned prompt files render byte-identically (ADR 0032).

Each ``legacy_*`` function is the inline f-string the call site used before the
move, copied verbatim; the rendered template must equal it exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from apps.api.app.study.generate import build_prompt
from apps.worker.app.ingest import steps
from apps.worker.app.knowledge import notes, papers
from packages.assessment import agents
from packages.assessment.models import GeneratedItem
from packages.assessment.validation import Excerpt, render_excerpts
from packages.knowledge.curriculum import prompt_listing
from packages.models.gateway import load_agent, user_prompt
from packages.prompts.contracts import PromptFile, load_prompt
from packages.prompts.templating import TemplateError, placeholders, render

PROMPTS = Path(__file__).resolve().parents[3] / "packages" / "prompts"
TRICKY = "Crazy paving {{native_text}} {not a var} }} {{ \\n é"
SOURCE = {"title": "Synthetic chest {{title}}"}
CHUNK = {"heading": None, "page_from": 3, "page_to": 4, "text": TRICKY}


def test_page_and_figure_prompts_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"page_no": 7, "native_text": TRICKY * 900}
    legacy = (f"Source title: {SOURCE['title']}\nPage: {page['page_no']}\n"
              f"Native text layer (may be empty or unordered):\n{page['native_text'][:12000]}")
    assert user_prompt("page_parse", source_title=SOURCE["title"], page_no="7",
                       native_text=page["native_text"][:12000]) == legacy
    fig = {"caption": TRICKY}
    assert user_prompt("image_case", figure_no="2", page_no="7", caption=fig["caption"]) \
        == f"Figure {2} on page {7}. Caption: {fig['caption']}"
    assert "user_prompt(\"page_parse\"" in Path(steps.__file__).read_text(encoding="utf-8")


def test_knowledge_prompts_are_unchanged() -> None:
    legacy_extract = (
        f"Source title: {SOURCE['title']}\nHeading path: {CHUNK['heading'] or '(none)'}\n"
        f"Pages: {CHUNK['page_from']}-{CHUNK['page_to']}\n\nChunk text:\n{CHUNK['text']}")
    assert notes._extract_prompt(SOURCE, CHUNK) == legacy_extract
    concepts = ["crazy paving", "PAP"]
    legacy_classify = (
        f"Allowed curriculum codes:\n{prompt_listing()}\n\n"
        f"Heading path: {CHUNK['heading'] or '(none)'}\n"
        f"Extracted concepts: {', '.join(concepts) or '(none)'}\n\nChunk text:\n{CHUNK['text']}")
    assert notes._classify_prompt(CHUNK, concepts) == legacy_classify
    assert "Extracted concepts: (none)" in notes._classify_prompt(CHUNK, [])


@pytest.mark.parametrize("with_image", [True, False])
def test_paper_prompt_is_unchanged(with_image: bool) -> None:
    from packages.curriculum.candidates import candidate_listing

    page = {"page_no": 5, "text": TRICKY * 900}
    image = "The rendered page image is attached; read it.\n" if with_image else ""
    nodes = candidate_listing(["frcr"])
    legacy = (f"Valid curriculum node ids:\n{nodes}\n\nSource title: {SOURCE['title']}\n"
              f"Page: {page['page_no']}\n{image}\nPage text:\n{page['text'][:12000]}")
    assert papers._prompt(SOURCE, page, with_image, "frcr") == legacy


def _excerpts() -> list[Excerpt]:
    return [Excerpt(ref="E1", heading="Synthetic heading", text=TRICKY,
                    citation={"kind": "chunk", "page_from": 1})]


@pytest.mark.parametrize("topic", ["PAP", None])
def test_assessment_prompts_are_unchanged(topic: str | None) -> None:
    ex = _excerpts()
    focus = f"Topic focus: {topic}\n" if topic else ""
    legacy = (
        f"Write {3} {agents.TYPE_LABELS['sba']} (type \"{'sba'}\") for "
        f"{agents.EXAM_TARGETS['frcr']}.\n{focus}"
        f"Supplied excerpt ids: {', '.join(e.ref for e in ex)}.\n"
        "Use only facts stated in the excerpts below; cite excerpt ids exactly.\n\n"
        f"{render_excerpts(ex)}")
    assert agents.generation_prompt(ex, "sba", "frcr", 3, topic) == legacy


def test_check_and_grade_prompts_are_unchanged() -> None:
    ex = _excerpts()
    item = GeneratedItem.model_construct(
        type="sba", topic="t", stem=TRICKY, options=[], key_index=-1, model_answer="",
        marking_scheme=[], key_findings=[], viva_turns=[], explanation="e", citations=["E1"],
        difficulty=2, cognitive_level="recall")
    legacy_check = ("Check this draft exam item against the supplied excerpts.\n\n"
                    f"<item>\n{item.model_dump_json(indent=1)}\n</item>\n\n"
                    f"{render_excerpts(ex)}")
    assert agents.check_prompt(item, ex) == legacy_check
    question = {"type": "seq", "stem": TRICKY,
                "answer": {"model_answer": TRICKY,
                           "marking_scheme": [{"point": "p {{x}}", "marks": 2}]}}
    scheme = [{"scheme_index": 0, "point": "p {{x}}", "marks": 2}]
    legacy_grade = (
        f"Question type: {question['type']}\n"
        f"<question>\n{question['stem']}\n</question>\n"
        f"<model_answer>\n{TRICKY}\n</model_answer>\n"
        f"<marking_scheme>\n{json.dumps(scheme, indent=1)}\n</marking_scheme>\n"
        f"<candidate_answer>\n{TRICKY[:agents.MAX_ANSWER_CHARS]}\n</candidate_answer>")
    assert agents.grade_prompt(question, TRICKY) == legacy_grade


def test_card_prompt_is_unchanged() -> None:
    chunks = [{"id": "c1", "heading": "H", "page_from": 1, "page_to": 2, "text": TRICKY}]
    payload = {"max_cards": 4, "curriculum_codes": ["A", "B"],
               "chunks": [{"id": "c1", "heading": "H", "pages": "1-2", "text": TRICKY}]}
    legacy = "Write recall cards from these chunks.\n" + json.dumps(payload, ensure_ascii=False)
    assert build_prompt(chunks, ["B", "A"], 4) == legacy


def test_renderer_is_strict_and_single_pass() -> None:
    assert render("a {{x}} b", {"x": "{{y}}"}) == "a {{y}} b"  # values are never expanded
    with pytest.raises(TemplateError):
        render("{{x}}", {})
    with pytest.raises(TemplateError):
        render("{{x}}", {"x": "1", "y": "2"})
    with pytest.raises(TemplateError):
        render("{{x}}", {"x": 1})  # type: ignore[dict-item]
    with pytest.raises(TemplateError):
        placeholders("{{ x }}")
    with pytest.raises(TemplateError):
        placeholders("{{x.__class__}}")


def test_templates_only_use_declared_inputs() -> None:
    base = load_prompt(PROMPTS / "page_parse" / "v2.yaml").model_dump()
    with pytest.raises(ValueError, match="undeclared"):
        PromptFile.model_validate({**base, "user_template": "{{secret_input}}"})
    moved = ["page_parse", "image_case", "knowledge_extract", "topic_classify", "paper_topics",
             "question_generate", "question_check", "seq_grade", "card_generate"]
    for name in moved:
        assert load_agent(name).prompt.user_template, name
