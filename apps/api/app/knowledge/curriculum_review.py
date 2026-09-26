"""Owner review of the packaged curriculum pack (tenant session, RLS; ADR 0023).

The pack file stays ``draft_pending_owner_approval``; the owner's decision is a
row in ``curriculum_reviews`` bound to the pack's content hash, so any edit to
the packaged tree shows as pending again. Decisions are append-only and
audited by id and hash only.
"""

from __future__ import annotations

from typing import Any

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.curriculum.candidates import tags_for
from packages.curriculum.contracts import CurriculumNode
from packages.curriculum.loader import radiology_hash, radiology_pack
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _node(node: CurriculumNode) -> dict[str, Any]:
    return {"code": node.code, "title": node.title, "level": node.level,
            "exams": list(node.exams), "children": []}


def tree(exam_target: str | None = None) -> list[dict[str, Any]]:
    """Systems with nested topics and subtopics, filtered by exam applicability."""
    wanted = tags_for([exam_target] if exam_target else None)
    built: dict[str, dict[str, Any]] = {}
    systems: list[dict[str, Any]] = []
    for node in radiology_pack().nodes:
        if node.level == "section" or not wanted & set(node.exams):
            continue
        item = _node(node)
        built[node.code] = item
        if node.level == "system":
            systems.append(item)
        elif node.parent_code in built:
            built[node.parent_code]["children"].append(item)
    return systems


async def history(session: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, pack_id, pack_version, content_hash, decision, notes, decided_at "
            "FROM curriculum_reviews WHERE pack_id = :p ORDER BY decided_at DESC, id LIMIT :n"
        ),
        {"p": radiology_pack().pack_id, "n": limit},
    )
    return [dict(r) for r in rows.mappings()]


async def status(session: AsyncSession) -> dict[str, Any]:
    """Pack metadata and the owner's latest decision on *this* content hash."""
    pack = radiology_pack()
    digest = radiology_hash()
    latest = next((r for r in await history(session, 50) if r["content_hash"] == digest), None)
    counts = {level: sum(n.level == level for n in pack.nodes)
              for level in ("system", "topic", "subtopic")}
    return {
        "pack_id": pack.pack_id, "version": pack.version, "pack_status": pack.status,
        "content_hash": digest, "source": pack.source, "sources": list(pack.sources),
        "counts": counts,
        "review_status": latest["decision"] if latest else "pending",
        "decided_at": latest["decided_at"] if latest else None,
        "notes": latest["notes"] if latest else "",
    }


async def decide(
    session: AsyncSession, principal: Principal, decision: str, content_hash: str, notes: str
) -> dict[str, Any]:
    """Record approve/reject of the pack version the owner reviewed."""
    pack = radiology_pack()
    if content_hash != radiology_hash():
        raise ValueError("the curriculum changed since it was reviewed; reload and decide again")
    await session.execute(
        text(
            "INSERT INTO curriculum_reviews (tenant_id, pack_id, pack_version, content_hash, "
            "decision, notes, decided_by) VALUES (:t, :p, :v, :h, :d, :n, :u)"
        ),
        {"t": principal.tenant_id, "p": pack.pack_id, "v": pack.version, "h": content_hash,
         "d": decision, "n": notes, "u": principal.user_id},
    )
    await audit(session, principal, f"knowledge.curriculum_{decision}", "curriculum_pack",
                pack.pack_id, {"version": pack.version, "content_hash": content_hash})
    result = await status(session)
    await session.commit()
    return result
