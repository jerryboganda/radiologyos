"""Concept notes, related figures, and the concept graph for the concept page.

Everything is scoped to the caller's own sources (tenant session, RLS): a
note is the caller's, built from the caller's claims; figures and graph edges
come only from the caller's sources. A note is ``current`` while its claims
hash matches the caller's claims now, ``stale`` otherwise; only a current note
on a concept with no open conflict can be marked verified (ADR 0030).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.knowledge.service import live_concept_id
from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from apps.worker.app.knowledge.depth_db import owner_claims
from packages.knowledge.synthesis import claims_hash
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class NoteNotVerifiable(ValueError):
    """The note is stale, superseded, already verified, or the concept has open conflicts."""


async def visible_concept(session: AsyncSession, user_id: UUID, concept_id: UUID) -> UUID | None:
    """The live concept id when the caller has a claim on it, else None."""
    concept_id = await live_concept_id(session, concept_id)
    found = (await session.execute(
        text("SELECT 1 FROM claims c JOIN sources s ON s.id = c.source_id WHERE "
             "c.concept_id = :c AND s.uploaded_by = :u AND s.deleted_at IS NULL LIMIT 1"),
        {"c": concept_id, "u": user_id},
    )).first()
    return concept_id if found else None


async def _open_conflicts(session: AsyncSession, user_id: UUID, concept_id: UUID) -> int:
    value: Any = (await session.execute(
        text("SELECT count(*) FROM knowledge_conflicts x JOIN claims a ON a.id = x.claim_a "
             "JOIN sources s ON s.id = a.source_id WHERE x.concept_id = :c "
             "AND x.status = 'open' AND s.uploaded_by = :u"),
        {"c": concept_id, "u": user_id},
    )).scalar_one()
    return int(value)


async def _latest_note(session: AsyncSession, user_id: UUID,
                       concept_id: UUID) -> dict[str, Any] | None:
    row = (await session.execute(
        text("SELECT id, version, claims_hash, status, body, sentences, dropped, "
             "agent_version, verified_at, created_at FROM concept_notes "
             "WHERE user_id = :u AND concept_id = :c "
             "ORDER BY (status <> 'superseded') DESC, version DESC LIMIT 1"),
        {"u": user_id, "c": concept_id},
    )).mappings().first()
    return dict(row) if row else None


async def note_state(session: AsyncSession, user_id: UUID,
                     concept_id: UUID) -> dict[str, Any] | None:
    live = await visible_concept(session, user_id, concept_id)
    if live is None:
        return None
    note = await _latest_note(session, user_id, live)
    digest = claims_hash(await owner_claims(session, user_id, live))
    conflicts = await _open_conflicts(session, user_id, live)
    state = "missing" if note is None else (
        "current" if note["claims_hash"] == digest else "stale")
    verifiable = bool(note and state == "current" and conflicts == 0
                      and note["status"] == "draft")
    public = {k: v for k, v in (note or {}).items() if k != "claims_hash"} or None
    return {"concept_id": live, "state": state, "open_conflicts": conflicts,
            "verifiable": verifiable, "note": public}


async def verify_note(session: AsyncSession, principal: Principal, concept_id: UUID,
                      note_id: UUID) -> dict[str, Any] | None:
    """Owner marks the exact current note version verified (audited)."""
    state = await note_state(session, principal.user_id, concept_id)
    if state is None:
        return None
    note = state["note"]
    if note is None or note["id"] != note_id:
        raise NoteNotVerifiable("that note version is not the latest")
    if not state["verifiable"]:
        raise NoteNotVerifiable("only a current draft on a concept without open conflicts "
                                "can be verified")
    await session.execute(
        text("UPDATE concept_notes SET status = 'verified', verified_by = :u, "
             "verified_at = now() WHERE id = :id AND user_id = :u"),
        {"u": principal.user_id, "id": note_id},
    )
    await audit(session, principal, "knowledge.note_verified", "concept_note", str(note_id),
                {"concept_id": str(state["concept_id"]), "version": note["version"]})
    result = await note_state(session, principal.user_id, concept_id)
    await session.commit()  # after the read: the tenant setting is transaction-local
    return result


async def related_figures(session: AsyncSession, user_id: UUID,
                          concept_id: UUID, limit: int = 8) -> list[dict[str, Any]]:
    """Figures on the pages the caller's claims about this concept cite."""
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT ON (f.id) f.id, f.source_id, s.title AS source_title, f.page_no,
                   f.caption, f.description, f.modality, f.anatomy, f.image_key
            FROM claims c
            JOIN sources s ON s.id = c.source_id AND s.uploaded_by = :u AND s.deleted_at IS NULL
            JOIN figures f ON f.source_id = c.source_id
                          AND f.page_no BETWEEN c.page_from AND c.page_to
            WHERE c.concept_id = :c AND f.image_key IS NOT NULL
            ORDER BY f.id LIMIT :n
            """
        ),
        {"u": user_id, "c": concept_id, "n": limit},
    )
    return [dict(r) for r in rows.mappings()]
