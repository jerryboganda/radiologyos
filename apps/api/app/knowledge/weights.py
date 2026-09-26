"""Topic-weight review/approval and extraction requests (tenant session, RLS).

Weights are per user: they come from that user's own past papers and only that
user can approve them. Approval is recorded in ``audit_log``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STEP = "knowledge_extraction"


async def list_weights(
    session: AsyncSession, user_id: UUID, exam_target: str | None
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT id, exam_target, curriculum_code, topic, weight, basis, approved,
                   approved_at, computed_at
            FROM topic_weights
            WHERE user_id = :u AND (CAST(:target AS text) IS NULL OR exam_target = :target)
            ORDER BY exam_target, (topic <> ''), weight DESC, curriculum_code, topic
            """
        ),
        {"u": user_id, "target": exam_target},
    )
    return [{**dict(r), "weight": float(r["weight"])} for r in rows.mappings()]


async def approve_weights(
    session: AsyncSession, principal: Principal, exam_target: str, ids: list[UUID] | None
) -> int:
    """Approve all current weights of an exam target, or only the listed ids."""
    result = await session.execute(
        text(
            """
            UPDATE topic_weights SET approved = true, approved_at = now(), approved_by = :u
            WHERE user_id = :u AND exam_target = :target AND approved = false
              AND (CAST(:ids AS uuid[]) IS NULL OR id = ANY(CAST(:ids AS uuid[])))
            RETURNING id
            """
        ),
        {"u": principal.user_id, "target": exam_target,
         "ids": list(ids) if ids is not None else None},
    )
    approved = len(result.fetchall())
    await audit(session, principal, "knowledge.weights_approved", "topic_weights",
                exam_target, {"count": approved})
    await session.commit()
    return approved


async def request_extraction(
    session: AsyncSession, principal: Principal, source_id: UUID
) -> UUID | None:
    """Reset the knowledge step of the source's latest ingest job to pending.

    Returns the ingest job id, or None when the caller does not own the source.
    Units already processed stay done (``knowledge_runs``), so a re-request only
    processes new or failed chunks/pages.
    """
    job = (
        await session.execute(
            text(
                """
                SELECT j.id, j.tenant_id, j.entity_id, j.pipeline_version FROM jobs j
                JOIN sources s ON s.id = j.entity_id
                WHERE j.entity_id = :s AND j.kind = 'ingest_source'
                  AND s.uploaded_by = :u AND s.deleted_at IS NULL
                ORDER BY j.pipeline_version DESC, j.created_at DESC LIMIT 1
                """
            ),
            {"s": source_id, "u": principal.user_id},
        )
    ).mappings().first()
    if job is None:
        return None
    await session.execute(
        text(
            """
            INSERT INTO job_steps (tenant_id, job_id, entity_id, step, pipeline_version, status)
            VALUES (:t, :j, :e, :step, :v, 'pending')
            ON CONFLICT (tenant_id, job_id, step, pipeline_version)
            DO UPDATE SET status = 'pending', error_code = NULL
            """
        ),
        {"t": job["tenant_id"], "j": job["id"], "e": job["entity_id"], "step": STEP,
         "v": job["pipeline_version"]},
    )
    await audit(session, principal, "knowledge.extract_requested", "source", str(source_id))
    await session.commit()
    return UUID(str(job["id"]))
