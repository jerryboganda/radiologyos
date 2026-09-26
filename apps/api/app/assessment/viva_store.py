"""SQL for viva sessions and turns (shared by the API and the worker).

Every statement runs in the caller's tenant transaction (RLS) and reads are
additionally scoped to the owning user. Session updates go through a fixed
column allow-list; values are always bound parameters.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.assessment.store import dumps
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_COLUMNS = (
    "id, tenant_id, user_id, kind, style, topic, figure_id, question_id, scenario, evidence, "
    "case_data, status, work, work_turn, runs, errors, error_code, level, miss_streak, "
    "max_turns, started_at, deadline_at, finished_at, stop_reason, debrief, pipeline_version, "
    "updated_at"
)
_TURN_COLUMNS = (
    "turn_no, stage, level, move, prompt, hint, expected, answer_text, answered_at, status, "
    "evaluation, pipeline_version"
)
_JSON = frozenset({"evidence", "case_data", "debrief"})
_UPDATABLE = frozenset({
    "status", "work", "work_turn", "runs", "errors", "error_code", "level", "miss_streak",
    "scenario", "topic", "case_data", "question_id", "finished_at", "stop_reason", "debrief",
})


async def insert_session(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, values: Mapping[str, Any]
) -> UUID:
    row = await session.execute(
        text(
            "INSERT INTO viva_sessions (tenant_id, user_id, kind, style, topic, figure_id, "
            "question_id, scenario, evidence, case_data, status, work, max_turns, started_at, "
            "deadline_at) VALUES (:t, :u, :kind, :style, :topic, :figure, :question, :scenario, "
            "CAST(:evidence AS jsonb), CAST(:case AS jsonb), :status, :work, :max_turns, "
            ":started, :deadline) RETURNING id"
        ),
        {"t": tenant_id, "u": user_id, "kind": values["kind"], "style": values["style"],
         "topic": values["topic"][:300], "figure": values.get("figure_id"),
         "question": values.get("question_id"), "scenario": values.get("scenario", ""),
         "evidence": dumps(values["evidence"]), "case": dumps(values.get("case_data", {})),
         "status": values["status"], "work": values["work"], "max_turns": values["max_turns"],
         "started": values["started_at"], "deadline": values.get("deadline_at")},
    )
    session_id: UUID = row.scalar_one()
    return session_id


async def load_session(
    session: AsyncSession, user_id: UUID | None, session_id: UUID, lock: bool = False
) -> dict[str, Any] | None:
    """One session; ``user_id`` None is the worker's read (the tenant context still applies)."""
    owner = "" if user_id is None else " AND user_id = :u"
    suffix = " FOR UPDATE" if lock else ""
    row = (
        await session.execute(
            text(f"SELECT {_SESSION_COLUMNS} FROM viva_sessions WHERE id = :s{owner}{suffix}"),  # nosec B608 - constant columns and suffixes; values are bound
            {"s": session_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def list_sessions(session: AsyncSession, user_id: UUID, limit: int) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(f"SELECT {_SESSION_COLUMNS} FROM viva_sessions WHERE user_id = :u "  # nosec B608 - constant column list; values are bound
             "ORDER BY started_at DESC LIMIT :n"),
        {"u": user_id, "n": limit},
    )
    return [dict(row) for row in rows.mappings()]


async def load_turns(session: AsyncSession, session_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(f"SELECT {_TURN_COLUMNS} FROM viva_turns WHERE session_id = :s ORDER BY turn_no"),  # nosec B608 - constant column list; values are bound
        {"s": session_id},
    )
    return [dict(row) for row in rows.mappings()]


async def insert_turn(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, session_id: UUID,
    turn: Mapping[str, Any],
) -> None:
    await session.execute(
        text(
            "INSERT INTO viva_turns (tenant_id, user_id, session_id, turn_no, stage, level, move, "
            "prompt, hint, expected) VALUES (:t, :u, :s, :n, :stage, :level, :move, :prompt, "
            ":hint, CAST(:expected AS jsonb)) "
            "ON CONFLICT (tenant_id, session_id, turn_no) DO NOTHING"
        ),
        {"t": tenant_id, "u": user_id, "s": session_id, "n": turn["turn_no"],
         "stage": turn.get("stage"), "level": turn["level"], "move": turn["move"],
         "prompt": turn["prompt"][:4000], "hint": turn.get("hint", "")[:2000],
         "expected": dumps(turn["expected"])},
    )


async def answer_turn(
    session: AsyncSession, session_id: UUID, turn_no: int, answer: str, at: datetime
) -> bool:
    row = await session.execute(
        text(
            "UPDATE viva_turns SET answer_text = :a, answered_at = :at, status = 'answered' "
            "WHERE session_id = :s AND turn_no = :n AND status = 'asked' RETURNING 1"
        ),
        {"a": answer, "at": at, "s": session_id, "n": turn_no},
    )
    return row.first() is not None


async def grade_turn(
    session: AsyncSession, session_id: UUID, turn_no: int, evaluation: Mapping[str, Any]
) -> None:
    await session.execute(
        text(
            "UPDATE viva_turns SET status = 'graded', evaluation = CAST(:e AS jsonb) "
            "WHERE session_id = :s AND turn_no = :n AND status = 'answered'"
        ),
        {"e": dumps(evaluation), "s": session_id, "n": turn_no},
    )


async def skip_open_turns(session: AsyncSession, session_id: UUID) -> None:
    """An unanswered or ungraded turn at the end of a session is kept, marked skipped."""
    await session.execute(
        text("UPDATE viva_turns SET status = 'skipped' WHERE session_id = :s "
             "AND status IN ('asked', 'answered')"),
        {"s": session_id},
    )


async def update_session(
    session: AsyncSession, session_id: UUID, values: Mapping[str, Any]
) -> None:
    unknown = set(values) - _UPDATABLE
    if unknown or not values:
        raise ValueError("unsupported viva session update")
    columns = sorted(values)
    assignments = ", ".join(
        f"{c} = CAST(:{c} AS jsonb)" if c in _JSON else f"{c} = :{c}" for c in columns)
    params = {c: dumps(values[c]) if c in _JSON else values[c] for c in columns}
    await session.execute(
        text(f"UPDATE viva_sessions SET {assignments} WHERE id = :sid"),  # nosec B608 - columns come from the fixed allow-list above; values are bound
        {**params, "sid": session_id},
    )


async def touch_stale_work(
    session: AsyncSession, user_id: UUID, session_id: UUID, pending_before: datetime,
    running_before: datetime,
) -> int | None:
    """Queued work untouched since ``pending_before``, or a run silent since
    ``running_before`` (its worker presumably died), is marked pending again so one
    reader re-queues it; returns its turn. A live run is left alone."""
    row = await session.execute(
        text(
            "UPDATE viva_sessions SET work = 'pending' WHERE id = :s AND user_id = :u "
            "AND ((work = 'pending' AND updated_at < :pb) "
            "OR (work = 'running' AND updated_at < :rb)) RETURNING work_turn"
        ),
        {"s": session_id, "u": user_id, "pb": pending_before, "rb": running_before},
    )
    found = row.first()
    return int(found[0]) if found else None


async def staged_question_for_figure(
    session: AsyncSession, user_id: UUID, figure_id: UUID
) -> dict[str, Any] | None:
    """The newest usable staged image case already built from this figure, if any."""
    row = (
        await session.execute(
            text(
                "SELECT id, topic, stem, answer, status FROM questions WHERE user_id = :u "
                "AND figure_id = :f AND type = 'image_case' AND answer -> 'stages' IS NOT NULL "
                "AND status <> 'retired' ORDER BY created_at DESC LIMIT 1"
            ),
            {"u": user_id, "f": figure_id},
        )
    ).mappings().first()
    return dict(row) if row else None
