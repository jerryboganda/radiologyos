"""SQL for grade disputes (ADR 0029). Every query runs under the tenant's RLS.

A user's own disputes are read with ``user_id``; the owner/admin queue reads
every open dispute of the tenant, with the disputed point and the user's own
answer read live from the stored exam result.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.assessment import store
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "d.id, d.user_id, d.exam_id, d.question_id, d.point_index, d.reason, d.marks, "
    "d.awarded_before, d.awarded_after, d.status, d.resolution_note, d.created_at, "
    "d.resolved_at"
)


async def insert(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, values: dict[str, Any]
) -> dict[str, Any] | None:
    """A new open dispute; None when this point was already disputed."""
    row = (
        await session.execute(
            text(
                "INSERT INTO grade_disputes AS d (tenant_id, user_id, exam_id, question_id, "
                "point_index, reason, marks, awarded_before) VALUES (:t, :u, :e, :q, :p, "
                ":reason, :marks, :before) ON CONFLICT DO NOTHING "
                f"RETURNING {_COLUMNS}"  # nosec B608 - constant column list; values are bound
            ),
            {"t": tenant_id, "u": user_id, "e": values["exam_id"], "q": values["question_id"],
             "p": values["point_index"], "reason": values["reason"],
             "marks": values["marks"], "before": values["awarded_before"]},
        )
    ).mappings().first()
    return dict(row) if row else None


async def list_for_exam(
    session: AsyncSession, user_id: UUID, exam_id: UUID
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM grade_disputes d WHERE d.user_id = :u "  # nosec B608 - constant column list; values are bound
            "AND d.exam_id = :e ORDER BY d.created_at, d.id"
        ),
        {"u": user_id, "e": exam_id},
    )
    return [dict(row) for row in rows.mappings()]


async def open_queue(session: AsyncSession, limit: int, offset: int) -> list[dict[str, Any]]:
    """Open disputes of the tenant, oldest first, with the exam's stored result."""
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS}, e.result, q.stem, q.topic FROM grade_disputes d "  # nosec B608 - constant column list; values are bound
            "JOIN exams e ON e.id = d.exam_id AND e.tenant_id = d.tenant_id "
            "LEFT JOIN questions q ON q.id = d.question_id AND q.tenant_id = d.tenant_id "
            "WHERE d.status = 'open' ORDER BY d.created_at, d.id LIMIT :n OFFSET :o"
        ),
        {"n": limit, "o": offset},
    )
    return [dict(row) for row in rows.mappings()]


async def lock(session: AsyncSession, dispute_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM grade_disputes d WHERE d.id = :d FOR UPDATE"),  # nosec B608 - constant column list; values are bound
            {"d": dispute_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def lock_exam_result(session: AsyncSession, exam_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT result FROM exams WHERE id = :e AND result IS NOT NULL FOR UPDATE"),
            {"e": exam_id},
        )
    ).first()
    return dict(row[0]) if row else None


async def save_exam_result(session: AsyncSession, exam_id: UUID, result: dict[str, Any]) -> None:
    await session.execute(
        text("UPDATE exams SET result = CAST(:r AS jsonb) WHERE id = :e"),
        {"r": store.dumps(result), "e": exam_id},
    )


async def resolve(
    session: AsyncSession, dispute_id: UUID, status: str, awarded_after: float | None,
    note: str, resolver: UUID,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE grade_disputes AS d SET status = :s, awarded_after = :a, "
                "resolution_note = :n, resolved_by = :r, resolved_at = now() "
                f"WHERE d.id = :d AND d.status = 'open' RETURNING {_COLUMNS}"  # nosec B608 - constant column list; values are bound
            ),
            {"s": status, "a": awarded_after, "n": note, "r": resolver, "d": dispute_id},
        )
    ).mappings().first()
    assert row is not None
    return dict(row)
