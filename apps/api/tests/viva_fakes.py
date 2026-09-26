"""Synthetic examiner outputs and snapshots for the viva tests (no real content)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apps.api.tests.test_assessment_validation import EXCERPTS
from packages.assessment.staged_case import STAGES
from packages.assessment.viva_steps import Snapshot

NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
CHECK_PASS = {"single_best_answer": True, "key_supported": True, "no_cueing": True,
              "distractors_plausible": True, "difficulty_agrees": True, "verdict": "pass",
              "reasons": []}


def question(text: str = "What pattern is shown?", cite: str = "E1",
             hint: str = "") -> dict[str, Any]:
    return {"question": text, "hint": hint,
            "expected_points": [{"point": "crazy paving", "citations": [cite]},
                                {"point": "septal thickening", "citations": [cite]}]}


def opening(cite: str = "F1") -> dict[str, Any]:
    return {"topic": "Pulmonary alveolar proteinosis", "scenario": "Look at this HRCT.",
            "citations": [cite], "question": question()}


def grade(statuses: tuple[str, ...] = ("matched", "matched"), unsafe: bool = False,
          escalate_cite: str = "E2", teach_cite: str = "E1") -> dict[str, Any]:
    return {
        "points": [{"index": i, "status": s, "justification": "said it"}
                   for i, s in enumerate(statuses)],
        "reasoning": 3, "communication": 2, "unsafe": unsafe,
        "feedback": "Name the distribution.",
        "teaching_point": {"text": "Crazy paving suggests PAP.", "citations": [teach_cite]},
        "escalate": question("Give three differentials.", escalate_cite),
        "probe": question("Look again at the septa. What do you see?", "E1",
                          hint="Consider the interlobular septa."),
    }


def staged_case(order: tuple[str, ...] = STAGES, cite: str = "E1") -> dict[str, Any]:
    return {
        "topic": "PAP", "stem": "A 40-year-old with dyspnoea. Look at this image.",
        "citations": ["F1"],
        "stages": [{"stage": stage, "model_answer": f"{stage} answer",
                    "points": [{"point": f"{stage} point", "marks": 2, "citations": [cite]}]}
                   for stage in order],
    }


def seq_grade(awarded: float = 2.0) -> dict[str, Any]:
    return {"points": [{"scheme_index": 0, "status": "matched" if awarded else "missed",
                        "awarded": awarded, "justification": "named it"}],
            "feedback": "Fine."}


def expected() -> list[dict[str, Any]]:
    cite = [{"ref": "E1", "kind": "chunk", "page_from": 2}]
    return [{"point": "crazy paving", "citations": cite},
            {"point": "septal thickening", "citations": cite}]


def viva_turn(turn_no: int, status: str = "answered", level: int = 1,
              evaluation: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"turn_no": turn_no, "stage": None, "level": level, "move": "open",
            "prompt": "What pattern is shown?", "hint": "", "expected": expected(),
            "answer_text": "Crazy paving with septal thickening", "status": status,
            "evaluation": evaluation}


def snap(**overrides: Any) -> Snapshot:
    values: dict[str, Any] = {
        "kind": "viva", "style": "practice", "topic": "PAP", "scenario": "Look at this HRCT.",
        "level": 1, "miss_streak": 0, "max_turns": 8, "deadline_at": NOW + timedelta(minutes=10),
        "case_data": {}, "evidence": EXCERPTS, "turns": [viva_turn(1)], "work_turn": 1,
        "errors": 0, "runs": 0,
    }
    return Snapshot(**{**values, **overrides})
