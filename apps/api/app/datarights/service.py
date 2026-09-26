"""Account export / deletion requests and export downloads (tenant session, RLS).

Every query is additionally scoped to the calling user, so one member of a
tenant never sees another member's exports. Requests and downloads are
audited by id only (ADR 0018).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DELETE_CONFIRMATION = "delete my account"
EXPORT_TTL_DAYS = 7
_COLUMNS = (
    "id, kind, status, step, byte_size, detail, error_code, created_at, finished_at, "
    "expires_at"
)


class AccountDeleting(RuntimeError):
    """The account is being deleted; no new exports."""


async def _active(session: AsyncSession, user_id: UUID, kind: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM data_jobs WHERE user_id = :u AND kind = :k "  # nosec B608 - constant column list
                "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1"
            ),
            {"u": user_id, "k": kind},
        )
    ).mappings().first()
    return dict(row) if row else None


async def request_job(
    session: AsyncSession, principal: Principal, kind: str
) -> tuple[dict[str, Any], bool]:
    """Create (or return the already active) export/delete job for the caller.

    Returns ``(job, created)``; the caller commits nothing else and enqueues.
    """
    if kind == "export" and await _active(session, principal.user_id, "delete"):
        raise AccountDeleting("account deletion is in progress")
    existing = await _active(session, principal.user_id, kind)
    if existing is not None:
        return existing, False
    row = (
        await session.execute(
            text(
                f"""
                INSERT INTO data_jobs (tenant_id, user_id, kind, expires_at)
                VALUES (:t, :u, :k, CASE WHEN :k = 'export'
                        THEN now() + make_interval(days => :ttl) END)
                ON CONFLICT (tenant_id, user_id, kind)
                    WHERE status IN ('queued', 'running') DO NOTHING
                RETURNING {_COLUMNS}
                """  # nosec B608 - constant column list
            ),
            {"t": principal.tenant_id, "u": principal.user_id, "k": kind,
             "ttl": EXPORT_TTL_DAYS},
        )
    ).mappings().first()
    if row is None:  # a concurrent request won the race
        again = await _active(session, principal.user_id, kind)
        if again is None:
            raise RuntimeError("data job vanished")
        return again, False
    action = "data.export_requested" if kind == "export" else "account.delete_requested"
    await audit(session, principal, action, "data_job", str(row["id"]))
    await session.commit()
    return dict(row), True


async def list_exports(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM data_jobs WHERE user_id = :u AND kind = 'export' "  # nosec B608 - constant column list
            "ORDER BY created_at DESC LIMIT 20"
        ),
        {"u": user_id},
    )
    return [dict(row) for row in rows.mappings()]


async def export_for_download(
    session: AsyncSession, principal: Principal, job_id: UUID
) -> dict[str, Any] | None:
    """The caller's finished, unexpired export (object key and size), audited."""
    row = (
        await session.execute(
            text(
                "SELECT id, object_key, byte_size, finished_at FROM data_jobs "
                "WHERE id = :id AND user_id = :u AND kind = 'export' "
                "AND status = 'succeeded' AND object_key IS NOT NULL AND expires_at > now()"
            ),
            {"id": job_id, "u": principal.user_id},
        )
    ).mappings().first()
    if row is None:
        return None
    await audit(session, principal, "data.export_downloaded", "data_job", str(job_id),
                {"bytes": row["byte_size"]})
    await session.commit()
    return dict(row)


def public_detail(detail: Any) -> dict[str, Any]:
    """Counts and ids only; detail never holds content, but keep it bounded."""
    if isinstance(detail, str):
        detail = json.loads(detail)
    return dict(detail) if isinstance(detail, dict) else {}
