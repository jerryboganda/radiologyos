"""Staged TOACS image case: fixed stages, a frozen cited rubric per stage, per-stage marks.

The candidate answers describe -> findings -> diagnosis -> differentials ->
next step, one stage at a time. Each stage's rubric (model answer plus
weighted, cited points) is written by ``image_case_stages`` from the figure
description and text excerpts before the candidate answers, checked like any
generated item (every citation must name a supplied excerpt), and frozen. A
stage answer is graded by the existing ``seq_grade`` grader against that
stage's points only; the model answer and its citations are revealed once the
stage is graded. The same rubric, flattened with a ``stage`` tag on every
point, is stored as an ``image_case`` bank question so the case can also sit
in an exam, where one structured answer is graded against all stages at once.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from packages.assessment.grading import apply_seq_grade
from packages.assessment.models import GeneratedItem, SchemeItem, SeqGrade
from packages.assessment.validation import Excerpt, check_item, resolve
from packages.assessment.viva_models import StagedCase

STAGES: tuple[str, ...] = ("describe", "findings", "diagnosis", "differentials", "next_step")
STAGE_LABELS: dict[str, str] = {
    "describe": "Describe", "findings": "Key findings", "diagnosis": "Most likely diagnosis",
    "differentials": "Differentials", "next_step": "Next step",
}
STAGE_PROMPTS: dict[str, str] = {
    "describe": "Describe the image: modality, plane or projection, window or sequence, "
                "and the region shown.",
    "findings": "What are the key findings?",
    "diagnosis": "What is the most likely diagnosis?",
    "differentials": "Give your differential diagnosis in order, with the feature that "
                     "separates each.",
    "next_step": "What is the next step in management or further imaging?",
}
STAGE_COMPETENCY: dict[str, str] = {
    "describe": "communication", "findings": "knowledge", "diagnosis": "knowledge",
    "differentials": "reasoning", "next_step": "reasoning",
}
_HEADING = re.compile(r"^\[(describe|findings|diagnosis|differentials|next_step)\]\s*$",
                      re.MULTILINE)


def validate_staged(case: StagedCase, supplied: Sequence[str]) -> list[str]:
    """Deterministic problems; an empty list means the rubric may be frozen."""
    problems: list[str] = []
    if tuple(s.stage for s in case.stages) != STAGES:
        problems.append("stages_out_of_order")
    if any(not s.model_answer.strip() for s in case.stages):
        problems.append("stage_model_answer_missing")
    problems += check_item(flattened_item(case), "image_case", supplied)
    return sorted(set(problems))


def flattened_item(case: StagedCase) -> GeneratedItem:
    """The case as one generated image-case item, for the shared checks and checker."""
    by_stage = {s.stage: s for s in case.stages}
    findings = by_stage.get("findings")
    diagnosis = by_stage.get("diagnosis")
    return GeneratedItem(
        type="image_case", topic=case.topic, stem=case.stem, options=[], key_index=-1,
        model_answer="\n".join(f"{STAGE_LABELS.get(s.stage, s.stage)}: {s.model_answer}"
                               for s in case.stages),
        marking_scheme=[SchemeItem(point=p.point, marks=p.marks, citations=p.citations)
                        for s in case.stages for p in s.points],
        key_findings=[p.point for p in findings.points] if findings else [],
        viva_turns=[], explanation=diagnosis.model_answer if diagnosis else "",
        citations=case.citations, difficulty=3, cognitive_level="analysis",
    )


def stage_rubric(case: StagedCase, excerpts: Sequence[Excerpt]) -> list[dict[str, Any]]:
    """Frozen per-stage rubric with resolved provenance (raises KeyError if uncited)."""
    return [
        {"stage": s.stage, "prompt": STAGE_PROMPTS[s.stage], "model_answer": s.model_answer,
         "marking_scheme": [
             {"point": p.point, "marks": p.marks, "citations": resolve(p.citations, excerpts),
              "stage": s.stage}
             for p in s.points]}
        for s in case.stages
    ]


def with_stages(answer: Mapping[str, Any], rubric: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A question answer carrying the stages, with a stage-tagged flattened scheme."""
    return {**answer, "stages": [dict(r) for r in rubric],
            "marking_scheme": [dict(p) for r in rubric for p in r["marking_scheme"]]}


def stage_question(stem: str, rubric: Mapping[str, Any]) -> dict[str, Any]:
    """A question-shaped mapping so one stage is graded by ``seq_grade`` alone."""
    return {"type": "image_case", "stem": f"{stem}\n\nStage: {rubric['prompt']}",
            "answer": {"model_answer": rubric["model_answer"],
                       "marking_scheme": rubric["marking_scheme"]}}


def stage_evaluation(rubric: Mapping[str, Any], grade: SeqGrade) -> dict[str, Any]:
    graded = apply_seq_grade(rubric["marking_scheme"], grade)
    fraction = graded["score"] / graded["max_score"] if graded["max_score"] else 0.0
    first = rubric["marking_scheme"][0]["citations"] if rubric["marking_scheme"] else []
    return {
        "verdict": "good" if fraction >= 0.75 else "partial" if fraction >= 0.4 else "miss",
        "score": graded["score"], "max_score": graded["max_score"],
        "scores": {STAGE_COMPETENCY[rubric["stage"]]: round(fraction, 4)},
        "points": graded["points"], "feedback": graded["feedback"],
        "model_answer": rubric["model_answer"],
        "teaching_point": {"text": rubric["model_answer"], "citations": first} if first else None,
    }


def stage_scores(points: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per-stage totals of graded scheme points that carry a ``stage`` tag."""
    totals: dict[str, dict[str, float]] = {}
    for point in points:
        stage = point.get("stage")
        if stage in STAGE_LABELS:
            t = totals.setdefault(str(stage), {"score": 0.0, "max_score": 0.0})
            t["score"] += float(point.get("awarded") or 0.0)
            t["max_score"] += float(point["marks"])
    return [{"stage": s, "score": round(totals[s]["score"], 2),
             "max_score": round(totals[s]["max_score"], 2)} for s in STAGES if s in totals]


def compose_answer(parts: Mapping[str, str]) -> str:
    """One structured exam answer from per-stage text (the web client does the same)."""
    return "\n".join(f"[{s}]\n{parts[s].strip()}" for s in STAGES if parts.get(s, "").strip())


def split_answer(text: str) -> dict[str, str]:
    """Inverse of ``compose_answer``; text before any heading is ignored."""
    marks = list(_HEADING.finditer(text))
    out: dict[str, str] = {}
    for i, match in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[match.end():end].strip()
        if body:
            out[match.group(1)] = body
    return out
