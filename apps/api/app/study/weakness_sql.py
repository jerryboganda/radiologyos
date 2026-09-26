"""SQL for the weakness loop, shared by practice attempts, Today sessions and exams.

Every statement runs in the caller's tenant transaction (RLS) and is scoped to the
calling user. An event is unique per (kind, attempt or review id), so recording
the same wrong answer twice creates nothing new. Only ids are logged, never text.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.study.service import citation_for
from packages.study import weakness
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CHUNK = """
    SELECT c.id, c.source_id, s.title AS source_title, c.page_from, c.page_to,
           c.heading, c.block_refs
    FROM chunks c JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
    WHERE s.uploaded_by = :u AND s.deleted_at IS NULL AND c.id = :c
"""
_CARD_INSERT = """
    INSERT INTO cards (tenant_id, user_id, source_id, source_chunk_id, curriculum_code, topic,
        front, back, origin, citation, state, due_at)
    VALUES (:t, :u, :source_id, :chunk_id, :code, :topic, :front, :back, 'weakness',
        CAST(:citation AS jsonb), 'learning', :due)
    RETURNING id
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


async def _scalar(session: AsyncSession, sql: str, params: dict[str, Any]) -> Any:
    return (await session.execute(text(sql), params)).scalar_one_or_none()


async def question_code(session: AsyncSession, user_id: UUID, question_id: UUID) -> str | None:
    """The question's curriculum node, resolved from the chunks it cites."""
    from apps.api.app.assessment.question_systems import QUESTION_SYSTEMS

    value = await _scalar(session, QUESTION_SYSTEMS + (
        "SELECT curriculum_code FROM qsys WHERE question_id = :q"),  # nosec B608 - constant SQL
        {"u": user_id, "q": question_id})
    return None if value is None else str(value)


async def _reset_card(session: AsyncSession, user_id: UUID, question_id: UUID,
                      due: datetime) -> UUID | None:
    card_id = await _scalar(session, (
        "SELECT card_id FROM weakness_events WHERE user_id = :u AND question_id = :q "
        "AND card_id IS NOT NULL ORDER BY created_at DESC LIMIT 1"),
        {"u": user_id, "q": question_id})
    if card_id is None:
        return None
    reset: UUID | None = await _scalar(session, (
        "UPDATE cards SET due_at = LEAST(due_at, :due) WHERE id = :c AND user_id = :u "
        "RETURNING id"), {"due": due, "c": card_id, "u": user_id})
    return reset


async def _create_card(session: AsyncSession, tenant_id: UUID, user_id: UUID,
                       question: Mapping[str, Any], code: str | None,
                       due: datetime) -> UUID | None:
    try:
        chunk_id = UUID(weakness.first_chunk_id(question.get("citations")) or "")
    except ValueError:
        return None
    found = (await session.execute(text(_CHUNK), {"u": user_id, "c": chunk_id})).mappings()
    chunk = found.first()
    if chunk is None:
        return None
    fields = weakness.card_text(question, str(chunk["heading"] or ""))
    created: UUID = await _scalar(session, _CARD_INSERT, {
        "t": tenant_id, "u": user_id, "source_id": chunk["source_id"], "chunk_id": chunk["id"],
        "code": weakness.card_code(code), "citation": _dumps(citation_for(dict(chunk))),
        "due": due, **fields})
    return created


async def record_wrong(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, question: Mapping[str, Any],
    kind: weakness.WeaknessKind, ref_id: UUID, now: datetime,
) -> UUID | None:
    """Create or reset the question's card and queue a re-test; None if already recorded."""
    seen = await _scalar(session, "SELECT id FROM weakness_events WHERE kind = :k "
                         "AND ref_id = :r", {"k": kind, "r": ref_id})
    if seen is not None:
        return None
    question_id = UUID(str(question["id"]))
    code = await question_code(session, user_id, question_id)
    due = weakness.due_at(now)
    card_id = await _reset_card(session, user_id, question_id, due)
    if card_id is None:
        card_id = await _create_card(session, tenant_id, user_id, question, code, due)
    event: UUID | None = await _scalar(session, (
        "INSERT INTO weakness_events (tenant_id, user_id, kind, ref_id, question_id, card_id, "
        "curriculum_code, retest_by) VALUES (:t, :u, :k, :r, :q, :c, :code, :by) "
        "ON CONFLICT (tenant_id, kind, ref_id) DO NOTHING RETURNING id"),
        {"t": tenant_id, "u": user_id, "k": kind, "r": ref_id, "q": question_id,
         "c": card_id, "code": code, "by": weakness.retest_by(now)})
    return event


async def record_lapse(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, card: Mapping[str, Any],
    review_id: UUID, now: datetime,
) -> UUID | None:
    """Queue a re-test of an active SBA question on the lapsed card's chunk, if any."""
    chunk_id = card.get("source_chunk_id")
    if chunk_id is None:
        return None
    cite = _dumps([{"kind": "chunk", "chunk_id": str(chunk_id)}])
    question_id = await _scalar(session, (
        "SELECT id FROM questions WHERE user_id = :u AND status = 'active' AND type = 'sba' "
        "AND citations @> CAST(:cite AS jsonb) ORDER BY created_at, id LIMIT 1"),
        {"u": user_id, "cite": cite})
    if question_id is None:
        return None
    event: UUID | None = await _scalar(session, (
        "INSERT INTO weakness_events (tenant_id, user_id, kind, ref_id, question_id, card_id, "
        "curriculum_code, retest_by) VALUES (:t, :u, 'card_lapse', :r, :q, :c, :code, :by) "
        "ON CONFLICT (tenant_id, kind, ref_id) DO NOTHING RETURNING id"),
        {"t": tenant_id, "u": user_id, "r": review_id, "q": question_id, "c": card["id"],
         "code": card.get("curriculum_code"), "by": weakness.retest_by(now)})
    return event


async def mark_retested(session: AsyncSession, user_id: UUID, question_id: UUID,
                        now: datetime) -> None:
    await session.execute(text(
        "UPDATE weakness_events SET retested_at = :now WHERE user_id = :u "
        "AND question_id = :q AND retested_at IS NULL"),
        {"now": now, "u": user_id, "q": question_id})


async def open_retests(session: AsyncSession, user_id: UUID, limit: int) -> list[dict[str, Any]]:
    rows = await session.execute(text(
        "SELECT id, question_id, retest_by FROM weakness_events WHERE user_id = :u "
        "AND retested_at IS NULL AND question_id IS NOT NULL "
        "ORDER BY retest_by, created_at, id LIMIT :n"), {"u": user_id, "n": limit})
    return [dict(row) for row in rows.mappings()]


async def after_sba(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, question: Mapping[str, Any],
    attempt_id: UUID | None, correct: bool, kind: weakness.WeaknessKind, now: datetime,
) -> None:
    """Close open re-tests of this question, then open a new one if it was wrong."""
    if attempt_id is None:
        return
    await mark_retested(session, user_id, UUID(str(question["id"])), now)
    if not correct:
        await record_wrong(session, tenant_id, user_id, question, kind, attempt_id, now)
