"""Owner review of Resolver decisions: list, decide, and undo merges (ADR 0030).

A decision is visible only to the user it was recorded for. Low-confidence
decisions wait in status ``review``; the owner merges or keeps them distinct.
Any applied merge can be undone. Every decision is audited by id only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.knowledge import merges
from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.knowledge.adjudication import choose_survivor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT = """
    SELECT m.id, m.concept_a, ka.name AS a_name, m.concept_b, kb.name AS b_name,
           m.similarity, m.decision, m.confidence, m.rationale, m.status, m.survivor,
           m.merged, m.agent_version, m.created_at, m.applied_at, m.undone_at, m.snapshot
    FROM concept_merges m
    JOIN concepts ka ON ka.id = m.concept_a
    JOIN concepts kb ON kb.id = m.concept_b
    WHERE m.user_id = :u
"""


def _public(row: Any) -> dict[str, Any]:
    out = dict(row)
    snapshot = out.pop("snapshot") or {}
    out["moved_claims"] = len(snapshot.get("claims") or [])
    out["similarity"] = float(out["similarity"])
    out["confidence"] = float(out["confidence"])
    return out


async def list_merges(session: AsyncSession, user_id: UUID, status: str | None,
                      limit: int = 200) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(_SELECT + " AND (CAST(:s AS text) IS NULL OR m.status = :s) "
             "ORDER BY m.created_at DESC LIMIT :n"),
        {"u": user_id, "s": status, "n": limit},
    )
    return [_public(r) for r in rows.mappings()]


async def _one(session: AsyncSession, user_id: UUID, merge_id: UUID) -> dict[str, Any] | None:
    row = (await session.execute(text(_SELECT + " AND m.id = :id"),
                                 {"u": user_id, "id": merge_id})).mappings().first()
    return dict(row) if row else None


async def _pair_rows(session: AsyncSession, merge: dict[str, Any]) -> list[dict[str, Any]]:
    rows = await session.execute(
        text("SELECT k.id, k.created_at, (SELECT count(*) FROM claims c "
             "WHERE c.concept_id = k.id) AS claim_count FROM concepts k WHERE k.id IN (:a, :b)"),
        {"a": merge["concept_a"], "b": merge["concept_b"]},
    )
    return [dict(r) for r in rows.mappings()]


async def decide(session: AsyncSession, principal: Principal, merge_id: UUID,
                 decision: str) -> dict[str, Any] | None:
    """Owner decision on a queued pair: ``merge`` applies it, ``distinct`` records it."""
    merge = await _one(session, principal.user_id, merge_id)
    if merge is None:
        return None
    if merge["status"] != "review":
        raise merges.MergeConflict("this pair is already decided")
    if decision == "merge":
        pair = await _pair_rows(session, merge)
        if len(pair) != 2:
            raise merges.MergeConflict("a concept no longer exists")
        survivor, merged = choose_survivor(pair[0], pair[1])
        await merges.apply_merge(session, merge_id, survivor["id"], merged["id"])
    else:
        await session.execute(
            text("UPDATE concept_merges SET status = 'distinct' WHERE id = :id"),
            {"id": merge_id})
    await session.execute(text("UPDATE concept_merges SET decided_by = :u WHERE id = :id"),
                          {"u": principal.user_id, "id": merge_id})
    await audit(session, principal, "knowledge.merge_decided", "concept_merge", str(merge_id),
                {"decision": decision})
    found = await _one(session, principal.user_id, merge_id)
    await session.commit()  # after the read: the tenant setting is transaction-local
    return _public(found) if found else None


async def undo(session: AsyncSession, principal: Principal,
               merge_id: UUID) -> dict[str, Any] | None:
    merge = await _one(session, principal.user_id, merge_id)
    if merge is None:
        return None
    if merge["status"] != "applied":
        raise merges.MergeConflict("only an applied merge can be undone")
    await merges.undo_merge(session, merge, principal.user_id)
    await audit(session, principal, "knowledge.merge_undone", "concept_merge", str(merge_id),
                {"survivor": str(merge["survivor"]), "merged": str(merge["merged"])})
    found = await _one(session, principal.user_id, merge_id)
    await session.commit()  # after the read: the tenant setting is transaction-local
    return _public(found) if found else None
