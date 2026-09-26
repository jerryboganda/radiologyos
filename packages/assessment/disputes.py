"""Grade disputes on auto-graded written exam points (no database, ADR 0029).

A user may dispute one marking-scheme point of a graded SEQ, image-case, or viva
item in a submitted exam when it did not earn full marks. The owner/admin then
accepts (the point's award is raised, never above its marks, and the item and
exam totals are recomputed from the stored result) or rejects it. The original
award is kept on the point as ``adjusted.awarded_before`` so the change is
visible in the result, and the dispute row keeps both numbers for the audit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.assessment.exam_result import FREE_TEXT_TYPES, fill_item
from packages.assessment.staged_case import stage_scores


class DisputeRefused(Exception):
    """A refusal with a stable, content-free ``code`` and an HTTP status."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def find_item(result: Mapping[str, Any] | None, question_id: str) -> dict[str, Any]:
    if not result:
        raise DisputeRefused("exam_not_submitted")
    item = next((i for i in result.get("items", []) if i["question_id"] == question_id), None)
    if item is None:
        raise DisputeRefused("item_not_found", 404)
    return dict(item)


def disputable_point(
    result: Mapping[str, Any] | None, question_id: str, point_index: int
) -> dict[str, Any]:
    """The point a new dispute may target, or a refusal."""
    item = find_item(result, question_id)
    if item.get("type") not in FREE_TEXT_TYPES:
        raise DisputeRefused("not_an_auto_graded_point", 422)
    if item.get("status") != "graded":
        raise DisputeRefused("item_not_graded")
    points = item.get("points") or []
    if not 0 <= point_index < len(points):
        raise DisputeRefused("point_not_found", 404)
    point = dict(points[point_index])
    if float(point["awarded"]) >= float(point["marks"]):
        raise DisputeRefused("point_has_full_marks")
    return point


def resolved_award(marks: float, before: float, requested: float | None) -> float:
    """The award an accepted dispute sets: full marks unless a value is given."""
    award = float(marks) if requested is None else float(requested)
    if not float(before) < award <= float(marks):
        raise DisputeRefused("award_out_of_range", 422)
    return round(award, 2)


def apply_award(
    result: Mapping[str, Any], question_id: str, point_index: int, awarded: float,
    dispute_id: str,
) -> dict[str, Any]:
    """Raise one point's award and recompute the item and exam totals."""
    item = find_item(result, question_id)
    points = [dict(point) for point in item.get("points") or []]
    if not 0 <= point_index < len(points):
        raise DisputeRefused("point_not_found", 404)
    point = points[point_index]
    marks = float(point["marks"])
    points[point_index] = {
        **point, "awarded": round(awarded, 2),
        "status": "matched" if awarded >= marks else "partial",
        "adjusted": {"dispute_id": dispute_id, "awarded_before": point["awarded"]},
    }
    item["points"] = points
    item["score"] = round(sum(float(p["awarded"]) for p in points), 2)
    staged = stage_scores(points)
    if staged:
        item["stage_scores"] = staged
    return fill_item(result, question_id, item)
