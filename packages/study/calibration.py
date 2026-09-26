"""Confidence calibration: self-rated confidence against actual SBA results.

Spec section 7: calibration is tracked separately and shown as a bias; it is
never folded into mastery. Each rated answer states a confidence of 1 (low),
2 (medium) or 3 (high), read as a stated chance of being right. The bias is
the mean of (stated - actual) over rated answers: positive means overconfident.
Confidently wrong answers (high confidence, wrong) are counted on their own,
because they are the errors most likely to repeat in the exam.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

STATED: dict[int, float] = {1: 0.4, 2: 0.65, 3: 0.9}
LABELS: dict[int, str] = {1: "low", 2: "medium", 3: "high"}
MIN_RATED = 10
TOLERANCE = 0.1

Verdict = Literal["insufficient", "overconfident", "underconfident", "calibrated"]


@dataclass(frozen=True, slots=True)
class Rated:
    confidence: int
    correct: float  # 0..1; partial marks allowed


def verdict(bias: float | None, rated: int) -> Verdict:
    if bias is None or rated < MIN_RATED:
        return "insufficient"
    if bias > TOLERANCE:
        return "overconfident"
    if bias < -TOLERANCE:
        return "underconfident"
    return "calibrated"


def _levels(answers: Sequence[Rated]) -> list[dict[str, Any]]:
    out = []
    for level, stated in STATED.items():
        mine = [a for a in answers if a.confidence == level]
        accuracy = sum(a.correct for a in mine) / len(mine) if mine else None
        out.append({"level": level, "label": LABELS[level], "stated": stated,
                    "answers": len(mine),
                    "accuracy": None if accuracy is None else round(accuracy, 4)})
    return out


def calibration(answers: Sequence[Rated]) -> dict[str, Any]:
    """Bias, per-level accuracy and confidently-wrong counts (no pass probability)."""
    valid = [Rated(a.confidence, min(max(a.correct, 0.0), 1.0))
             for a in answers if a.confidence in STATED]
    bias = (sum(STATED[a.confidence] - a.correct for a in valid) / len(valid)
            if valid else None)
    wrong = [a for a in valid if a.correct < 1.0]
    confident_wrong = sum(1 for a in wrong if a.confidence == 3)
    return {
        "rated": len(valid),
        "bias": None if bias is None else round(bias, 4),
        "verdict": verdict(bias, len(valid)),
        "levels": _levels(valid),
        "wrong": len(wrong),
        "confident_wrong": confident_wrong,
        "confident_wrong_share": round(confident_wrong / len(wrong), 4) if wrong else None,
        "min_rated": MIN_RATED,
    }
