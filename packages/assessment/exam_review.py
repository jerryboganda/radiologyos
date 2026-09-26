"""Exam results review: time per item, confidence, and calibration (no database).

The exam screen reports each item's active seconds and an optional 1-3
confidence in the same compare-and-set autosave as the answers. Seconds only
grow (a stale tab cannot shrink them) and are capped at the exam's elapsed
time; confidence is optional per item. On submission every result item carries
``time_seconds`` and ``confidence``, and the summary carries a ``review``
block: timing totals, the slowest items, and a calibration table that compares
stated confidence with the score fraction actually earned. Pending (ungraded)
and failed items are left out of calibration until they have a score. No pass
probability is computed.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from statistics import median
from typing import Any

from packages.study.calibration import LABELS, STATED

MAX_ITEM_SECONDS = 6 * 60 * 60
SLOWEST = 3
CONFIDENTLY_WRONG_BELOW = 0.5


class ReviewInputError(ValueError):
    """An autosave carried seconds or confidence the exam cannot accept."""


def merge_seconds(
    saved: Mapping[str, int], incoming: Mapping[str, int], allowed: Collection[str],
    elapsed_seconds: float,
) -> dict[str, int]:
    """Keep the larger count per item, capped at the exam's elapsed time."""
    cap = int(max(0.0, min(float(MAX_ITEM_SECONDS), elapsed_seconds + 60)))
    merged = {key: int(value) for key, value in saved.items()}
    for question_id, seconds in incoming.items():
        if question_id not in allowed:
            raise ReviewInputError("time for a question outside this exam")
        if not 0 <= int(seconds) <= MAX_ITEM_SECONDS:
            raise ReviewInputError("item time is out of range")
        merged[question_id] = min(max(merged.get(question_id, 0), int(seconds)), cap)
    return merged


def merge_confidence(
    saved: Mapping[str, int], incoming: Mapping[str, int | None], allowed: Collection[str]
) -> dict[str, int]:
    """Set (1-3) or clear (None) confidence per item."""
    merged = {key: int(value) for key, value in saved.items()}
    for question_id, level in incoming.items():
        if question_id not in allowed:
            raise ReviewInputError("confidence for a question outside this exam")
        if level is None:
            merged.pop(question_id, None)
        elif level in STATED:
            merged[question_id] = int(level)
        else:
            raise ReviewInputError("confidence must be 1, 2 or 3")
    return merged


def annotate(
    item: dict[str, Any], seconds: Mapping[str, int], confidence: Mapping[str, int]
) -> dict[str, Any]:
    question_id = item["question_id"]
    return {**item, "time_seconds": seconds.get(question_id),
            "confidence": confidence.get(question_id)}


def fraction(item: Mapping[str, Any]) -> float | None:
    """The share of the item's marks earned, or None while it has no score."""
    if item.get("status", "graded") != "graded" or item.get("score") is None:
        return None
    maximum = float(item.get("max_score") or 0.0)
    return float(item["score"]) / maximum if maximum else None


def timing(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    timed = [(str(i["question_id"]), int(i["time_seconds"])) for i in items
             if isinstance(i.get("time_seconds"), int)]
    values = [seconds for _, seconds in timed]
    slow = sorted(timed, key=lambda pair: (-pair[1], pair[0]))[:SLOWEST]
    return {
        "timed_items": len(timed),
        "total_seconds": sum(values),
        "mean_seconds": round(sum(values) / len(values), 1) if values else None,
        "median_seconds": float(median(values)) if values else None,
        "slowest": [{"question_id": qid, "seconds": seconds} for qid, seconds in slow],
    }


def calibration(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    levels: dict[int, list[float]] = {level: [] for level in STATED}
    for item in items:
        level, earned = item.get("confidence"), fraction(item)
        if level in STATED and earned is not None:
            levels[int(level)].append(earned)
    rated = sum(len(values) for values in levels.values())
    gaps = [STATED[level] - earned for level, values in levels.items() for earned in values]
    return {
        "rated": rated,
        "levels": [
            {"level": level, "label": LABELS[level], "stated": STATED[level],
             "count": len(values),
             "mean_score": round(sum(values) / len(values), 3) if values else None}
            for level, values in levels.items()
        ],
        "bias": round(sum(gaps) / len(gaps), 3) if gaps else None,
        "confidently_wrong": sum(1 for earned in levels[3] if earned < CONFIDENTLY_WRONG_BELOW),
        "unsure_right": sum(1 for earned in levels[1] if earned >= 0.999),
    }


def review_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"timing": timing(items), "calibration": calibration(items)}
