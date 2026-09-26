"""Grade disputes: open (the exam's owner), resolve (owner/admin), audited (ADR 0029).

Accepting a dispute raises the disputed point's award in the stored exam result
and recomputes the item and exam totals in the same transaction; the attempt row
stays the append-only record of the machine grade. Audit entries carry ids and
numbers only, never answers, reasons, or notes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.assessment import dispute_store, exams
from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.assessment.disputes import (
    DisputeRefused,
    apply_award,
    disputable_point,
    find_item,
    resolved_award,
)
from sqlalchemy.ext.asyncio import AsyncSession

RESOLVER_ROLES = ("org_admin", "superadmin")


def _ids(dispute: dict[str, Any]) -> dict[str, Any]:
    return {"exam_id": str(dispute["exam_id"]), "question_id": str(dispute["question_id"]),
            "point_index": int(dispute["point_index"])}


async def open_dispute(
    session: AsyncSession, principal: Principal, exam_id: UUID, question_id: UUID,
    point_index: int, reason: str,
) -> dict[str, Any]:
    row = await exams.load_exam(session, principal.user_id, exam_id)
    if row is None:
        raise DisputeRefused("exam_not_found", 404)
    if row["submitted_at"] is None:
        raise DisputeRefused("exam_not_submitted")
    point = disputable_point(row["result"], str(question_id), point_index)
    created = await dispute_store.insert(session, principal.tenant_id, principal.user_id, {
        "exam_id": exam_id, "question_id": question_id, "point_index": point_index,
        "reason": reason.strip(), "marks": float(point["marks"]),
        "awarded_before": float(point["awarded"])})
    if created is None:
        raise DisputeRefused("already_disputed")
    await audit(session, principal, "grade_dispute.opened", "grade_dispute",
                str(created["id"]), _ids(created))
    return created


async def _accept(
    session: AsyncSession, principal: Principal, dispute: dict[str, Any],
    awarded: float | None, note: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    award = resolved_award(dispute["marks"], dispute["awarded_before"], awarded)
    result = await dispute_store.lock_exam_result(session, dispute["exam_id"])
    question_id, index = str(dispute["question_id"]), int(dispute["point_index"])
    points = find_item(result, question_id).get("points") or []
    if index >= len(points) or float(points[index]["awarded"]) != float(
            dispute["awarded_before"]):
        raise DisputeRefused("point_changed_since_dispute")
    assert result is not None
    updated_result = apply_award(result, question_id, index, award, str(dispute["id"]))
    await dispute_store.save_exam_result(session, dispute["exam_id"], updated_result)
    updated = await dispute_store.resolve(session, dispute["id"], "accepted", award, note,
                                          principal.user_id)
    await audit(session, principal, "grade_dispute.accepted", "grade_dispute",
                str(dispute["id"]), {
                    **_ids(dispute), "awarded_before": float(dispute["awarded_before"]),
                    "awarded_after": award, "score_before": result.get("score"),
                    "score_after": updated_result.get("score")})
    return updated, updated_result


async def resolve_dispute(
    session: AsyncSession, principal: Principal, dispute_id: UUID, action: str,
    awarded: float | None, note: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Accept (adjust the score) or reject one open dispute; returns (dispute, result)."""
    dispute = await dispute_store.lock(session, dispute_id)
    if dispute is None:
        raise DisputeRefused("dispute_not_found", 404)
    if dispute["status"] != "open":
        raise DisputeRefused("dispute_closed")
    if action == "accept":
        return await _accept(session, principal, dispute, awarded, note.strip())
    updated = await dispute_store.resolve(session, dispute_id, "rejected", None, note.strip(),
                                          principal.user_id)
    await audit(session, principal, "grade_dispute.rejected", "grade_dispute",
                str(dispute_id), _ids(dispute))
    return updated, None


def queue_entry(row: dict[str, Any]) -> dict[str, Any]:
    """A queue row with the disputed point and the user's answer from the stored result."""
    item: dict[str, Any] = next((i for i in (row.get("result") or {}).get("items", [])
                                 if i["question_id"] == str(row["question_id"])), {})
    points = item.get("points") or []
    index = int(row["point_index"])
    point = points[index] if index < len(points) else {}
    return {**{k: v for k, v in row.items() if k not in ("result", "stem", "topic")},
            "stem": row.get("stem") or "", "topic": row.get("topic") or item.get("topic", ""),
            "point": point.get("point", ""), "justification": point.get("justification", ""),
            "citations": point.get("citations") or [], "answer_text": item.get("answer_text", ""),
            "model_answer": item.get("model_answer", "")}
