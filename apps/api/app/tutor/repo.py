"""Tutor thread persistence.

Every query runs in the caller's transaction-local tenant session (RLS) and is
additionally scoped to the thread owner, so one member of a tenant never sees
another member's tutor conversations.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from packages.tutor.models import GroundedAnswer
from packages.tutor.orchestrator import Turn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TITLE_CHARS = 120
HISTORY_MESSAGES = 6


def thread_title(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1] + "…"


async def get_thread(
    session: AsyncSession, user_id: UUID, thread_id: UUID
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT id, title, created_at, updated_at FROM tutor_threads "
                 "WHERE id = :id AND user_id = :u"),
            {"id": thread_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def list_threads(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT t.id, t.title, t.created_at, t.updated_at,
                   (SELECT count(*) FROM tutor_messages m
                     WHERE m.thread_id = t.id AND m.tenant_id = t.tenant_id) AS message_count
            FROM tutor_threads t
            WHERE t.user_id = :u
            ORDER BY t.updated_at DESC
            LIMIT 200
            """
        ),
        {"u": user_id},
    )
    return [dict(row) for row in rows.mappings()]


async def thread_messages(session: AsyncSession, thread_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text("SELECT id, role, content, citations, grounding, agent_version, created_at "
             "FROM tutor_messages WHERE thread_id = :t ORDER BY created_at, id"),
        {"t": thread_id},
    )
    return [dict(row) for row in rows.mappings()]


async def recent_history(session: AsyncSession, thread_id: UUID) -> list[Turn]:
    rows = await session.execute(
        text("SELECT role, content FROM tutor_messages WHERE thread_id = :t "
             "ORDER BY created_at DESC, id DESC LIMIT :n"),
        {"t": thread_id, "n": HISTORY_MESSAGES},
    )
    return [Turn(role=r["role"], content=r["content"]) for r in reversed(rows.mappings().all())]


async def create_thread(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, title: str
) -> UUID:
    row = await session.execute(
        text("INSERT INTO tutor_threads (tenant_id, user_id, title) "
             "VALUES (:t, :u, :title) RETURNING id"),
        {"t": tenant_id, "u": user_id, "title": title},
    )
    thread_id: UUID = row.scalar_one()
    return thread_id


async def add_exchange(
    session: AsyncSession, tenant_id: UUID, thread_id: UUID, question: str,
    answer: GroundedAnswer,
) -> UUID:
    """Store the question and its grounded answer; return the answer's id."""
    await session.execute(
        text("INSERT INTO tutor_messages (tenant_id, thread_id, role, content) "
             "VALUES (:t, :th, 'user', :c)"),
        {"t": tenant_id, "th": thread_id, "c": question},
    )
    segments = [segment.model_dump(mode="json") for segment in answer.segments]
    row = await session.execute(
        text(
            "INSERT INTO tutor_messages (tenant_id, thread_id, role, content, citations, "
            "grounding, agent_version, created_at) VALUES (:t, :th, 'assistant', :c, "
            "CAST(:cit AS jsonb), :g, :v, clock_timestamp()) RETURNING id"
        ),
        {"t": tenant_id, "th": thread_id, "c": answer.text, "g": answer.grounding,
         "v": answer.agent_version, "cit": json.dumps(segments, ensure_ascii=False)},
    )
    await session.execute(
        text("UPDATE tutor_threads SET updated_at = now() WHERE id = :th"), {"th": thread_id}
    )
    message_id: UUID = row.scalar_one()
    return message_id
