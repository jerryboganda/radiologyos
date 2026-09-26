"""Prompt assembly and calls for the assessment agents.

All three agents go through ``packages.models.gateway.run_agent`` (named route,
versioned prompt, schema-validated output). User content (excerpts, candidate
answers) is wrapped in tagged data blocks and never logged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from packages.assessment.models import GeneratedItem, GeneratedQuestions, QuestionCheck, SeqGrade
from packages.assessment.validation import Excerpt, render_excerpts
from packages.models.gateway import Transport, run_agent

EXAM_TARGETS: dict[str, str] = {
    "fcps2_theory": "FCPS-II Radiology theory (CPSP): SBA/BCQ and SEQ papers",
    "fcps2_toacs": "FCPS-II Radiology TOACS/clinical: image stations, spotters, and viva",
    "imm": "IMM (CPSP Intermediate Module) Radiology",
    "frcr": "FRCR (Royal College of Radiologists): SBA, rapid reporting, long cases, oral",
}
TYPE_LABELS: dict[str, str] = {
    "sba": "single best answer (SBA/BCQ) MCQs",
    "seq": "short essay questions (SEQ) with a weighted marking scheme",
    "image_case": "TOACS-style image cases (spotter station)",
    "viva": "viva voce question chains",
}
MAX_ANSWER_CHARS = 8000


def generation_prompt(
    excerpts: Sequence[Excerpt], item_type: str, exam_target: str, count: int, topic: str | None
) -> str:
    focus = f"Topic focus: {topic}\n" if topic else ""
    return (
        f"Write {count} {TYPE_LABELS[item_type]} (type \"{item_type}\") for "
        f"{EXAM_TARGETS[exam_target]}.\n{focus}"
        f"Supplied excerpt ids: {', '.join(e.ref for e in excerpts)}.\n"
        "Use only facts stated in the excerpts below; cite excerpt ids exactly.\n\n"
        f"{render_excerpts(excerpts)}"
    )


def check_prompt(item: GeneratedItem, excerpts: Sequence[Excerpt]) -> str:
    return (
        "Check this draft exam item against the supplied excerpts.\n\n"
        f"<item>\n{item.model_dump_json(indent=1)}\n</item>\n\n"
        f"{render_excerpts(excerpts)}"
    )


def grade_prompt(question: Mapping[str, Any], answer_text: str) -> str:
    answer = question["answer"]
    scheme = [
        {"scheme_index": i, "point": p["point"], "marks": p["marks"]}
        for i, p in enumerate(answer.get("marking_scheme", []))
    ]
    return (
        f"Question type: {question['type']}\n"
        f"<question>\n{question['stem']}\n</question>\n"
        f"<model_answer>\n{answer.get('model_answer', '')}\n</model_answer>\n"
        f"<marking_scheme>\n{json.dumps(scheme, indent=1)}\n</marking_scheme>\n"
        f"<candidate_answer>\n{answer_text[:MAX_ANSWER_CHARS]}\n</candidate_answer>"
    )


def generate(
    transport: Transport,
    excerpts: Sequence[Excerpt],
    item_type: str,
    exam_target: str,
    count: int,
    topic: str | None = None,
) -> GeneratedQuestions:
    prompt = generation_prompt(excerpts, item_type, exam_target, count, topic)
    parsed, _ = run_agent(transport, "question_generate", prompt)
    return cast(GeneratedQuestions, parsed)


def check(transport: Transport, item: GeneratedItem, excerpts: Sequence[Excerpt]) -> QuestionCheck:
    parsed, _ = run_agent(transport, "question_check", check_prompt(item, excerpts))
    return cast(QuestionCheck, parsed)


def grade_free_text(
    transport: Transport, question: Mapping[str, Any], answer_text: str
) -> SeqGrade:
    parsed, _ = run_agent(transport, "seq_grade", grade_prompt(question, answer_text))
    return cast(SeqGrade, parsed)
