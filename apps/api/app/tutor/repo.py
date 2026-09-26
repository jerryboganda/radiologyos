"""Tutor thread persistence.

Every query runs in the caller's transaction-local tenant session (RLS) and is
additionally scoped to the thread owner, so one member of a tenant never sees
another member's tutor conversations.

An assistant message stores its verified answer in ``citations`` (jsonb, which
migration 0005 constrains to an array): the segments in order, then — since ADR
0013 v2 — one trailing ``{"kind": "judge_stats", "judge": {...},
"dropped_segments": n}`` element. Rows written before v2 have no such element;
``stored_answer`` reads both, so no migration is needed.

Since ADR 0025 a user message may name the image it asked about (``image_id``),
and a thread keeps a rolling summary of its older messages (``memory_*``
columns, migration 0017); the summary is context only, never a citation.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from packages.tutor.memory import MemoryState, MemoryUpdate
from packages.tutor.models import GroundedAnswer
from packages.tutor.prompts import Turn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TITLE_CHARS = 120
HISTORY_MESSAGES = 6
# At most this many uncovered messages are read per ask; memory folds keep it small.
UNCOVERED_CAP = 200
MEMORY_CHARS = 4000


JUDGE_STATS = "judge_stats"


def stored_citations(answer: GroundedAnswer) -> list[dict[str, Any]]:
    """The jsonb array for an answer: segments, then its judge stats element."""
    stored: list[dict[str, Any]] = [s.model_dump(mode="json") for s in answer.segments]
    if answer.judge is not None:
        stored.append({"kind": JUDGE_STATS, "judge": answer.judge.model_dump(mode="json"),
                       "dropped_segments": answer.dropped_segments})
    return stored


def stored_answer(citations: Any) -> tuple[list[Any], Any]:
    """Return (segments, judge stats) from a stored ``citations`` array (any version)."""
    segments: list[Any] = []
    judge: Any = None
    for item in citations or []:
        if isinstance(item, dict) and item.get("kind") == JUDGE_STATS:
            judge = item.get("judge")
        else:
            segments.append(item)
    return segments, judge


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
        text("SELECT m.id, m.role, m.content, m.citations, m.grounding, m.agent_version, "
             "m.created_at, m.image_id, i.reading AS image_reading "
             "FROM tutor_messages m LEFT JOIN tutor_images i "
             "ON i.id = m.image_id AND i.tenant_id = m.tenant_id "
             "WHERE m.thread_id = :t ORDER BY m.created_at, m.id"),
        {"t": thread_id},
    )
    return [dict(row) for row in rows.mappings()]


async def memory_state(session: AsyncSession, thread_id: UUID) -> MemoryState:
    """The thread's rolling summary and every message it does not cover yet (ADR 0025)."""
    row = (
        await session.execute(
            text("SELECT memory_summary, memory_covered FROM tutor_threads WHERE id = :t"),
            {"t": thread_id},
        )
    ).mappings().first()
    if row is None:
        return MemoryState()
    covered = int(row["memory_covered"])
    rows = await session.execute(
        text("SELECT role, content FROM tutor_messages WHERE thread_id = :t "
             "ORDER BY created_at, id OFFSET :n LIMIT :cap"),
        {"t": thread_id, "n": covered, "cap": UNCOVERED_CAP},
    )
    turns = tuple(Turn(role=r["role"], content=r["content"]) for r in rows.mappings())
    return MemoryState(summary=str(row["memory_summary"]), covered=covered, uncovered=turns)


async def save_memory(session: AsyncSession, thread_id: UUID, update: MemoryUpdate) -> None:
    await session.execute(
        text("UPDATE tutor_threads SET memory_summary = :s, memory_covered = :n, "
             "memory_version = :v WHERE id = :t AND memory_covered < :n"),
        {"t": thread_id, "s": update.summary[:MEMORY_CHARS], "n": update.covered,
         "v": update.agent_version},
    )


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
    answer: GroundedAnswer, image_id: UUID | None = None,
) -> UUID:
    """Store the question (with its attached image, if any) and grounded answer.

    Returns the answer's id.
    """
    await session.execute(
        text("INSERT INTO tutor_messages (tenant_id, thread_id, role, content, image_id) "
             "VALUES (:t, :th, 'user', :c, :img)"),
        {"t": tenant_id, "th": thread_id, "c": question, "img": image_id},
    )
    stored = stored_citations(answer)
    row = await session.execute(
        text(
            "INSERT INTO tutor_messages (tenant_id, thread_id, role, content, citations, "
            "grounding, agent_version, created_at) VALUES (:t, :th, 'assistant', :c, "
            "CAST(:cit AS jsonb), :g, :v, clock_timestamp()) RETURNING id"
        ),
        {"t": tenant_id, "th": thread_id, "c": answer.text, "g": answer.grounding,
         "v": answer.agent_version, "cit": json.dumps(stored, ensure_ascii=False)},
    )
    await session.execute(
        text("UPDATE tutor_threads SET updated_at = now() WHERE id = :th"), {"th": thread_id}
    )
    message_id: UUID = row.scalar_one()
    return message_id
