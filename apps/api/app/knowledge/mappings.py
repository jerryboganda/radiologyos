"""Curriculum-mapping review queue (tenant session, RLS; ADR 0016/0018).

Low-confidence classifier mappings land in status ``review``. The owner of the
source accepts, rejects, or re-codes each one; every decision is audited by id
and code only. A mapping is visible only when its source belongs to the caller.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.knowledge.curriculum import pack, system_codes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT = """
    SELECT m.id, m.source_id, s.title AS source_title, m.page_from, m.page_to,
           m.curriculum_code, m.topic, m.confidence, m.status, m.agent_version, m.created_at,
           left(coalesce(ch.text, ''), 400) AS excerpt
    FROM curriculum_mappings m
    JOIN sources s ON s.id = m.source_id
    LEFT JOIN chunks ch ON ch.id = m.chunk_id
    WHERE s.uploaded_by = :u AND s.deleted_at IS NULL
"""


def curriculum_systems() -> list[dict[str, str]]:
    return [{"code": n.code, "title": n.title} for n in pack().nodes if n.level == "system"]


async def list_mappings(
    session: AsyncSession, user_id: UUID, status: str, limit: int
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(_SELECT + " AND m.status = :status "
             "ORDER BY s.title, m.page_from, m.confidence DESC LIMIT :limit"),
        {"u": user_id, "status": status, "limit": limit},
    )
    return [{**dict(r), "confidence": float(r["confidence"])} for r in rows.mappings()]


async def _one(session: AsyncSession, user_id: UUID, mapping_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(text(_SELECT + " AND m.id = :id"), {"u": user_id, "id": mapping_id})
    ).mappings().first()
    return {**dict(row), "confidence": float(row["confidence"])} if row else None


async def decide(
    session: AsyncSession, principal: Principal, mapping_id: UUID, decision: str,
    code: str | None = None,
) -> dict[str, Any] | None:
    """Apply accept | reject | code; returns the resulting mapping or None if not visible.

    Re-coding onto a code the same unit already carries merges into that row
    (it is accepted; this one is rejected), so the unique key never collides.
    """
    found = await _one(session, principal.user_id, mapping_id)
    if found is None:
        return None
    target = mapping_id
    if decision == "code":
        if code not in system_codes():
            raise ValueError("unknown curriculum code")
        target = await _recode(session, mapping_id, code)
    else:
        status = "accepted" if decision == "accept" else "rejected"
        await session.execute(
            text("UPDATE curriculum_mappings SET status = :s WHERE id = :id"),
            {"s": status, "id": mapping_id},
        )
    await audit(session, principal, "knowledge.mapping_decided", "curriculum_mapping",
                str(mapping_id), {"decision": decision, "code": code or found["curriculum_code"]})
    result = await _one(session, principal.user_id, target)
    await session.commit()
    return result


async def _recode(session: AsyncSession, mapping_id: UUID, code: str) -> UUID:
    duplicate = (
        await session.execute(
            text(
                """
                SELECT d.id FROM curriculum_mappings d
                JOIN curriculum_mappings m ON m.id = :id
                WHERE d.id <> m.id AND d.source_id = m.source_id AND d.unit_hash = m.unit_hash
                  AND d.curriculum_code = :code AND d.topic = m.topic
                """
            ),
            {"id": mapping_id, "code": code},
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        await session.execute(
            text("UPDATE curriculum_mappings SET status = CASE WHEN id = :keep "
                 "THEN 'accepted' ELSE 'rejected' END WHERE id IN (:keep, :drop)"),
            {"keep": duplicate, "drop": mapping_id},
        )
        return UUID(str(duplicate))
    await session.execute(
        text("UPDATE curriculum_mappings SET curriculum_code = :code, status = 'accepted' "
             "WHERE id = :id"),
        {"code": code, "id": mapping_id},
    )
    return mapping_id
