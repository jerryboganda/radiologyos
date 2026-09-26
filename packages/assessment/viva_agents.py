"""Prompt assembly and calls for the viva examiner and staged image-case agents.

Every call goes through ``packages.models.gateway.run_agent`` (named route,
versioned prompt, schema-validated output). Excerpts and candidate answers are
wrapped in tagged data blocks; they are sent to the model and never logged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from packages.assessment.validation import Excerpt, render_excerpts
from packages.assessment.viva_models import StagedCase, VivaOpening, VivaTurnGrade
from packages.models.gateway import Transport, run_agent

STYLES: dict[str, str] = {
    "practice": "a structured radiology viva for self-practice",
    "fcps2_toacs": "an FCPS-II Radiology (CPSP) TOACS/viva station: short, focused, "
                   "one examiner, one case",
    "frcr_2b_oral": "an FRCR 2B oral: case-based, brisk, moving from observation to "
                    "diagnosis to management",
}
LEVELS = {1: "recognition", 2: "key findings and mechanism", 3: "differentials",
          4: "management and complications", 5: "pitfalls and consultant-level nuance"}
MAX_ANSWER_CHARS = 4000
MAX_TRANSCRIPT_TURNS = 8


def _header(style: str, excerpts: Sequence[Excerpt]) -> str:
    return (f"Viva format: {STYLES[style]}.\n"
            f"Supplied excerpt ids: {', '.join(e.ref for e in excerpts)}.\n")


def open_prompt(excerpts: Sequence[Excerpt], style: str, topic: str, level: int) -> str:
    focus = f"Topic focus: {topic}\n" if topic else ""
    return (
        _header(style, excerpts) + focus +
        f"Open the viva at level {level} ({LEVELS[level]}).\n\n{render_excerpts(excerpts)}"
    )


def _transcript(turns: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for turn in list(turns)[-MAX_TRANSCRIPT_TURNS:]:
        verdict = (turn.get("evaluation") or {}).get("verdict", "")
        lines.append(
            f"<turn no=\"{turn['turn_no']}\" level=\"{turn['level']}\" verdict=\"{verdict}\">\n"
            f"<examiner>{turn['prompt']}</examiner>\n"
            f"<candidate_answer>{str(turn.get('answer_text') or '')[:MAX_ANSWER_CHARS]}"
            "</candidate_answer>\n</turn>"
        )
    return "<transcript>\n" + "\n".join(lines) + "\n</transcript>" if lines else ""


def turn_prompt(
    excerpts: Sequence[Excerpt], style: str, scenario: str,
    earlier: Sequence[Mapping[str, Any]], current: Mapping[str, Any], answer: str,
) -> str:
    expected = [{"index": i, "point": p["point"]} for i, p in enumerate(current["expected"])]
    level = int(current["level"])
    deeper = min(5, level + 1)
    return (
        _header(style, excerpts) +
        f"<scenario>\n{scenario}\n</scenario>\n{_transcript(earlier)}\n"
        f"Current question (level {level}, {LEVELS[level]}):\n"
        f"<question>\n{current['prompt']}\n</question>\n"
        f"<expected_points>\n{json.dumps(expected, indent=1)}\n</expected_points>\n"
        f"<candidate_answer>\n{answer[:MAX_ANSWER_CHARS]}\n</candidate_answer>\n"
        f"escalate: level {deeper} ({LEVELS[deeper]}). probe: stay on level {level}.\n\n"
        f"{render_excerpts(excerpts)}"
    )


def stages_prompt(excerpts: Sequence[Excerpt], style: str, topic: str) -> str:
    focus = f"Topic focus: {topic}\n" if topic else ""
    return (
        _header(style, excerpts) + focus +
        "Write the staged station for the figure excerpt (F1).\n\n" + render_excerpts(excerpts)
    )


def open_viva(
    transport: Transport, excerpts: Sequence[Excerpt], style: str, topic: str, level: int
) -> VivaOpening:
    parsed, _ = run_agent(transport, "viva_open", open_prompt(excerpts, style, topic, level))
    return cast(VivaOpening, parsed)


def grade_turn(
    transport: Transport, excerpts: Sequence[Excerpt], style: str, scenario: str,
    earlier: Sequence[Mapping[str, Any]], current: Mapping[str, Any], answer: str,
) -> VivaTurnGrade:
    prompt = turn_prompt(excerpts, style, scenario, earlier, current, answer)
    parsed, _ = run_agent(transport, "viva_examiner", prompt)
    return cast(VivaTurnGrade, parsed)


def write_stages(
    transport: Transport, excerpts: Sequence[Excerpt], style: str, topic: str
) -> StagedCase:
    parsed, _ = run_agent(transport, "image_case_stages", stages_prompt(excerpts, style, topic))
    return cast(StagedCase, parsed)
