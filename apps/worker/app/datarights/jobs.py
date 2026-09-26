"""``data_jobs`` state for the export and delete workers (tenant session, RLS).

Only ids, step names, counts, and error class names are stored or logged,
never content (hard rule 4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from packages.library.storage import ObjectStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

EXPORT_TTL = timedelta(days=7)


@dataclass(slots=True)
class DataDeps:
    engine: AsyncEngine
    store: ObjectStore


async def load(session: AsyncSession, job_id: UUID, kind: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, user_id, kind, status, step, detail, object_key "
                "FROM data_jobs WHERE id = :id AND kind = :kind"
            ),
            {"id": job_id, "kind": kind},
        )
    ).mappings().first()
    return dict(row) if row else None


async def start(session: AsyncSession, job_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE data_jobs SET status = 'running', attempts = attempts + 1, "
            "error_code = NULL WHERE id = :id"
        ),
        {"id": job_id},
    )


async def set_step(
    session: AsyncSession, job_id: UUID, step: str, detail: dict[str, Any] | None = None
) -> None:
    await session.execute(
        text(
            "UPDATE data_jobs SET step = :step, "
            "detail = detail || CAST(:detail AS jsonb) WHERE id = :id"
        ),
        {"id": job_id, "step": step, "detail": json.dumps(detail or {})},
    )


async def finish(
    session: AsyncSession,
    job_id: UUID,
    detail: dict[str, Any],
    object_key: str | None = None,
    byte_size: int | None = None,
) -> bool:
    """Mark success; an export stays downloadable for ``EXPORT_TTL``.

    False when the row is gone (the account was erased meanwhile).
    """
    result: Any = await session.execute(
        text(
            """
            UPDATE data_jobs SET status = 'succeeded', step = 'done', finished_at = now(),
                detail = detail || CAST(:detail AS jsonb),
                object_key = COALESCE(:key, object_key),
                byte_size = COALESCE(:size, byte_size),
                expires_at = CASE WHEN kind = 'export'
                    THEN now() + make_interval(days => :ttl) ELSE expires_at END
            WHERE id = :id
            """
        ),
        {"id": job_id, "detail": json.dumps(detail), "key": object_key, "size": byte_size,
         "ttl": EXPORT_TTL.days},
    )
    return bool(result.rowcount)


async def account_deleting(session: AsyncSession, user_id: UUID) -> bool:
    """True once the user asked to delete their account: no new exports then."""
    found = await session.execute(
        text(
            "SELECT 1 FROM data_jobs WHERE user_id = :u AND kind = 'delete' "
            "AND status IN ('queued', 'running', 'succeeded') LIMIT 1"
        ),
        {"u": user_id},
    )
    return found.first() is not None


async def fail(engine: AsyncEngine, tenant_id: UUID, job_id: UUID, code: str,
               final: bool) -> None:
    """Record an error class; a non-final failure stays queued for the retry."""
    from apps.worker.app.ingest.db import tenant_tx

    async with tenant_tx(engine, tenant_id) as session:
        await session.execute(
            text(
                "UPDATE data_jobs SET status = :status, error_code = :code, "
                "finished_at = CASE WHEN :final THEN now() ELSE NULL END WHERE id = :id"
            ),
            {"id": job_id, "code": code[:100], "final": final,
             "status": "failed" if final else "queued"},
        )
