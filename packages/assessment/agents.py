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
from packages.models.gateway import Transport, run_agent, user_prompt

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
    return user_prompt(
        "question_generate", count=str(count), type_label=TYPE_LABELS[item_type],
        item_type=item_type, exam_target=EXAM_TARGETS[exam_target],
        topic_focus=f"Topic focus: {topic}\n" if topic else "",
        excerpt_ids=", ".join(e.ref for e in excerpts), excerpts=render_excerpts(excerpts),
    )


def check_prompt(item: GeneratedItem, excerpts: Sequence[Excerpt]) -> str:
    return user_prompt("question_check", item=item.model_dump_json(indent=1),
                       excerpts=render_excerpts(excerpts))


def grade_prompt(question: Mapping[str, Any], answer_text: str) -> str:
    answer = question["answer"]
    scheme = [
        {"scheme_index": i, "point": p["point"], "marks": p["marks"]}
        for i, p in enumerate(answer.get("marking_scheme", []))
    ]
    return user_prompt(
        "seq_grade", question_type=str(question["type"]), question=str(question["stem"]),
        model_answer=str(answer.get("model_answer", "")),
        marking_scheme=json.dumps(scheme, indent=1),
        candidate_answer=answer_text[:MAX_ANSWER_CHARS],
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
