"""Approve, reject, or edit a draft question (owner review, audited).

* approve: only a draft with no deterministic problems whose cited source
  pages and figures still exist becomes ``active``;
* reject: a draft (or an active item) becomes ``retired`` with a reason;
* edit: wording of a draft changes, the deterministic checks re-run on the
  stored shape, and the item stays ``draft`` until approved.

Audit rows carry the action, the question id, and edited field names only,
never question text.
"""

from __future__ import annotations

from typing import Any

from apps.api.app.assessment import review_store
from apps.api.app.core.time import now_utc
from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.assessment.review import apply_edits, stored_problems
from sqlalchemy.ext.asyncio import AsyncSession


class ReviewRefused(Exception):
    """``code`` is a stable, content-free reason; ``status`` the HTTP status to use."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _stamp(question: dict[str, Any], action: str, **extra: Any) -> dict[str, Any]:
    quality = dict(question.get("quality") or {})
    history = list(quality.get("reviews") or [])[-9:]
    history.append({"action": action, "at": now_utc().isoformat(), **extra})
    quality["reviews"] = history
    return {**question, "quality": quality}


async def _approve(session: AsyncSession, principal: Principal,
                   question: dict[str, Any]) -> dict[str, Any]:
    if question["status"] != "draft":
        raise ReviewRefused("not_a_draft")
    problems = stored_problems(question)
    if problems:
        raise ReviewRefused(",".join(problems), 422)
    if not await review_store.citations_valid(session, principal.user_id, question):
        raise ReviewRefused("citations_stale")
    return {**_stamp(question, "approve"), "status": "active"}


def _reject(question: dict[str, Any]) -> dict[str, Any]:
    if question["status"] == "retired":
        raise ReviewRefused("already_retired")
    return {**_stamp(question, "reject"), "status": "retired"}


def _edit(question: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    if question["status"] != "draft":
        raise ReviewRefused("not_a_draft")
    if question["type"] != "sba" and ("options" in edits or "key_index" in edits):
        raise ReviewRefused("options_only_for_sba", 422)
    if question["type"] == "sba" and "model_answer" in edits:
        raise ReviewRefused("model_answer_not_for_sba", 422)
    try:
        edited = apply_edits(question, edits)
    except ValueError as exc:
        raise ReviewRefused(str(exc), 422) from exc
    problems = stored_problems(edited)
    if problems:
        raise ReviewRefused(",".join(problems), 422)
    return _stamp(edited, "edit", fields=sorted(edits))


async def review(
    session: AsyncSession, principal: Principal, question: dict[str, Any], action: str,
    edits: dict[str, Any],
) -> dict[str, Any]:
    """Apply one review action to a locked question row and audit it."""
    reason: str | None
    if action == "approve":
        updated = await _approve(session, principal, question)
        reason = "owner_approved"
    elif action == "reject":
        updated, reason = _reject(question), "rejected_in_review"
    else:
        updated, reason = _edit(question, edits), question.get("status_reason")
    await review_store.save_review(session, principal.user_id, updated, reason)
    await audit(session, principal, f"question.review_{action}", "question",
                str(question["id"]), {"fields": sorted(edits)} if edits else {})
    return updated
