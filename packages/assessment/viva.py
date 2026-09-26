"""Viva examiner rules: verdicts, escalation, stop rules, scoring, debrief (no I/O).

The model grades an answer point by point against the frozen, cited expected
points of the current question and proposes two follow-ups (escalate, probe).
Everything that decides the session is plain code here: the verdict comes from
the fraction of expected points matched (an unsafe answer is always a miss),
the next move and difficulty level follow the section 8 persona rules
(escalate one level per good answer, probe with a hint on a weak one), and the
session stops after two consecutive misses, at the turn limit, or at the
deadline. Citations fail closed: an expected point or teaching point with no
citation to a supplied excerpt is dropped, and a question left with no cited
point cannot be asked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from packages.assessment.validation import Excerpt
from packages.assessment.viva_models import ExaminerQuestion, TeachingPoint, VivaTurnGrade

PIPELINE_VERSION = 1
MAX_LEVEL = 5
MISS_LIMIT = 2
GOOD_AT = 0.75
PARTIAL_AT = 0.4
Verdict = Literal["good", "partial", "miss"]
MoveKind = Literal["escalate", "probe"]
StopReason = Literal[
    "max_turns", "time_up", "two_consecutive_misses", "ended_by_candidate",
    "stages_complete", "examiner_error",
]
COMPETENCIES: tuple[tuple[str, str], ...] = (
    ("knowledge", "Knowledge"),
    ("reasoning", "Reasoning and differentials"),
    ("communication", "Communication and structure"),
)
_CREDIT = {"matched": 1.0, "partial": 0.5, "missed": 0.0}


@dataclass(frozen=True, slots=True)
class Move:
    kind: MoveKind
    level: int
    miss_streak: int


def citation_map(excerpts: Sequence[Excerpt]) -> dict[str, dict[str, Any]]:
    return {e.ref: {"ref": e.ref, **e.citation} for e in excerpts}


def resolve_supplied(
    ids: Iterable[str], by_ref: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve supplied ids in first-seen order; unknown ids are dropped, never trusted."""
    seen: list[str] = []
    for ref in ids:
        if ref in by_ref and ref not in seen:
            seen.append(ref)
    return [dict(by_ref[ref]) for ref in seen]


def cited_expected(
    question: ExaminerQuestion, by_ref: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expected points that keep at least one supplied citation ([] means: do not ask)."""
    points = []
    for item in question.expected_points:
        cites = resolve_supplied(item.citations, by_ref)
        if cites and item.point.strip():
            points.append({"point": item.point.strip(), "citations": cites})
    return points


def cited_teaching(
    point: TeachingPoint, by_ref: Mapping[str, dict[str, Any]]
) -> dict[str, Any] | None:
    cites = resolve_supplied(point.citations, by_ref)
    if not cites or not point.text.strip():
        return None
    return {"text": point.text.strip(), "citations": cites}


def knowledge_fraction(statuses: Mapping[int, str], expected_count: int) -> float:
    if expected_count <= 0:
        return 0.0
    credit = sum(_CREDIT[statuses.get(i, "missed")] for i in range(expected_count))
    return round(credit / expected_count, 4)


def verdict_of(fraction: float, unsafe: bool) -> Verdict:
    if unsafe or fraction < PARTIAL_AT:
        return "miss"
    return "good" if fraction >= GOOD_AT else "partial"


def next_move(verdict: Verdict, level: int, miss_streak: int) -> Move:
    """Escalate one level on a good answer; probe (same level, or one lower on a miss)."""
    if verdict == "good":
        return Move("escalate", min(MAX_LEVEL, level + 1), 0)
    if verdict == "partial":
        return Move("probe", level, 0)
    return Move("probe", max(1, level - 1), miss_streak + 1)


def stop_reason(
    answered: int, max_turns: int, miss_streak: int, now: datetime, deadline: datetime | None
) -> StopReason | None:
    if miss_streak >= MISS_LIMIT:
        return "two_consecutive_misses"
    if answered >= max_turns:
        return "max_turns"
    if deadline is not None and now >= deadline:
        return "time_up"
    return None


def evaluate_turn(
    grade: VivaTurnGrade, expected: Sequence[Mapping[str, Any]],
    by_ref: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Normalise one examiner grade against the frozen expected points (they are authoritative)."""
    first: dict[int, Any] = {}
    for check in grade.points:
        if 0 <= check.index < len(expected):
            first.setdefault(check.index, check)
    statuses = {index: check.status for index, check in first.items()}
    fraction = knowledge_fraction(statuses, len(expected))
    points = [
        {"point": item["point"], "citations": item["citations"],
         "status": statuses.get(i, "missed"),
         "justification": first[i].justification if i in first else ""}
        for i, item in enumerate(expected)
    ]
    return {
        "verdict": verdict_of(fraction, grade.unsafe),
        "scores": {"knowledge": fraction, "reasoning": round(grade.reasoning / 4, 4),
                   "communication": round(grade.communication / 4, 4)},
        "unsafe": grade.unsafe,
        "points": points,
        "feedback": grade.feedback.strip(),
        "teaching_point": cited_teaching(grade.teaching_point, by_ref),
    }


def _percent(values: Sequence[float]) -> float | None:
    return round(100.0 * sum(values) / len(values), 1) if values else None


def competency_scores(evaluations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for key, label in COMPETENCIES:
        values = [float(e["scores"][key]) for e in evaluations if key in e.get("scores", {})]
        out.append({"key": key, "label": label, "percent": _percent(values),
                    "turns": len(values)})
    return out


def teaching_points(turns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Cited teaching points, weak turns first, one per distinct text."""
    graded = [t for t in turns if t.get("evaluation")]
    ordered = sorted(graded, key=lambda t: (t["evaluation"].get("verdict") == "good",
                                            t["turn_no"]))
    seen: set[str] = set()
    out = []
    for turn in ordered:
        point = turn["evaluation"].get("teaching_point")
        if point and point["citations"] and point["text"].casefold() not in seen:
            seen.add(point["text"].casefold())
            out.append({**point, "turn_no": turn["turn_no"],
                        "verdict": turn["evaluation"].get("verdict")})
    return out


def weak_turns(turns: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [t for t in turns if (t.get("evaluation") or {}).get("verdict") in ("miss", "partial")]


def debrief(
    turns: Sequence[Mapping[str, Any]], stop: StopReason, kind: str
) -> dict[str, Any]:
    """Final debrief: per-competency scores, stage scores (image case), cited teaching points."""
    graded = [t for t in turns if t.get("status") == "graded" and t.get("evaluation")]
    evaluations = [t["evaluation"] for t in graded]
    competencies = competency_scores(evaluations)
    stages = [
        {"stage": t["stage"], "score": t["evaluation"]["score"],
         "max_score": t["evaluation"]["max_score"]}
        for t in graded if t.get("stage")
    ]
    if kind == "image_case":
        total = sum(float(s["max_score"]) for s in stages)
        overall = round(100.0 * sum(float(s["score"]) for s in stages) / total, 1) if total else 0.0
    else:
        known = [c["percent"] for c in competencies if c["percent"] is not None]
        overall = round(sum(known) / len(known), 1) if known else 0.0
    good = [int(t["level"]) for t in graded if t["evaluation"].get("verdict") == "good"]
    return {
        "stop_reason": stop,
        "turns_answered": len(graded),
        "overall_percent": overall,
        "level_reached": max(good, default=0),
        "competencies": competencies,
        "stages": stages,
        "teaching_points": teaching_points(graded),
        "weak_turns": [t["turn_no"] for t in weak_turns(graded)],
    }
