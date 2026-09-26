"""Conflict verdicts and "trust source" decisions (ADR 0030).

The owner of a conflict (the uploader of claim A's source, as in
``service.list_conflicts``) chooses **trust A**, **trust B**, or **both valid in
context**. Trusting one side keeps it ``active`` and marks the other
``superseded``; "both" keeps both ``active``. Every decision is audited by id
only. The Conflict agent's verdict is stored beside the heuristic one, and a
confident "context"/"same" verdict closes the conflict with both claims kept.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.knowledge.service import list_conflicts
from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TRUST_TEXT = {"a": "Trusted source A", "b": "Trusted source B",
              "both": "Both valid in context"}


async def close_conflict(
    session: AsyncSession, conflict: dict[str, Any], resolution: str,
    preferred: UUID | None, user_id: UUID | None, trust: str | None,
) -> None:
    """Resolve one open conflict and restore claim statuses (no commit)."""
    await session.execute(
        text(
            "UPDATE knowledge_conflicts SET status = 'resolved', resolution = :r, "
            "preferred_claim = :p, resolved_by = :u, resolved_at = now(), trust = :trust "
            "WHERE id = :id"
        ),
        {"r": resolution[:2000], "p": preferred, "u": user_id, "trust": trust,
         "id": conflict["id"]},
    )
    for claim_id in (conflict["a_id"], conflict["b_id"]):
        status = "active"
        if preferred is not None and claim_id != preferred:
            status = "superseded"
        await session.execute(
            text(
                "UPDATE claims SET status = :s WHERE id = :id AND NOT EXISTS ("
                "SELECT 1 FROM knowledge_conflicts x WHERE x.status = 'open' "
                "AND :id IN (x.claim_a, x.claim_b))"
            ),
            {"s": status, "id": claim_id},
        )


async def trust_conflict(
    session: AsyncSession, principal: Principal, conflict_id: UUID, trust: str, note: str,
) -> dict[str, Any] | None:
    """Apply the owner's trust decision; None when the conflict is not visible."""
    found = [c for c in await list_conflicts(session, principal.user_id, None)
             if c["id"] == conflict_id]
    if not found:
        return None
    conflict = found[0]
    if conflict["status"] != "open":
        raise ValueError("conflict is already resolved")
    preferred = {"a": conflict["a_id"], "b": conflict["b_id"]}.get(trust)
    resolution = TRUST_TEXT[trust] + (f": {note.strip()}" if note.strip() else "")
    await close_conflict(session, conflict, resolution, preferred, principal.user_id, trust)
    await audit(session, principal, "knowledge.conflict_trusted", "knowledge_conflict",
                str(conflict_id), {"trust": trust, "preferred_claim": str(preferred or "")})
    # Read back before the commit: the tenant setting is transaction-local.
    refreshed = [c for c in await list_conflicts(session, principal.user_id, None)
                 if c["id"] == conflict_id]
    await session.commit()
    return refreshed[0] if refreshed else None


async def store_verdict(
    session: AsyncSession, conflict_id: UUID, verdict: dict[str, Any], agent: str
) -> None:
    await session.execute(
        text(
            "UPDATE knowledge_conflicts SET ai_label = :l, ai_confidence = :c, "
            "ai_rationale = :r, ai_context = :ctx, ai_cites = CAST(:cites AS text[]), "
            "ai_agent_version = :agent WHERE id = :id"
        ),
        {"l": verdict["label"], "c": verdict["confidence"], "r": verdict["rationale"][:1000],
         "ctx": verdict["context"][:300], "cites": list(verdict["cites"]), "agent": agent,
         "id": conflict_id},
    )
