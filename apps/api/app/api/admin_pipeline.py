"""Owner controls for the library pipeline (ADR 0037): status, pause, approve.

* ``GET  /v1/admin/pipeline``          - pause state and progress counts.
* ``POST /v1/admin/pipeline/pause``    - stop model work between saved units.
* ``POST /v1/admin/pipeline/resume``   - continue where it stopped.
* ``POST /v1/admin/pipeline/approve``  - send the items GPT-6 Luna and Sol could
  not answer to Claude Opus 5.5 high (the owner's explicit OK, "collect & ask").
* ``POST /v1/admin/pipeline/dismiss``  - close those items without using Claude.

Admins only; counts and names, never content.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, Response
from packages.pipeline import state
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/admin/pipeline", tags=["admin"])
PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
ADMIN_ROLES = ("org_admin", "superadmin")
MINE = "SELECT id FROM sources WHERE uploaded_by = :u AND deleted_at IS NULL"
COUNTS = {
    "pages": f"SELECT vision_status AS k, count(*) AS n FROM source_pages "
             f"WHERE source_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
    "jobs": f"SELECT status AS k, count(*) AS n FROM jobs WHERE kind = 'ingest_source' "
            f"AND entity_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
    "knowledge_units": f"SELECT status AS k, count(*) AS n FROM knowledge_runs "
                       f"WHERE source_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
    "awaiting_owner": f"SELECT agent AS k, count(*) AS n FROM model_escalations "
                      f"WHERE status = 'pending' AND source_id IN ({MINE}) GROUP BY 1",  # nosec B608 - constant SQL
}  # nosec B608 - constant SQL built from the constant MINE subquery


class PipelineStatus(BaseModel):
    paused: str | None  # None | "manual" | "quota"
    resume_at: float | None
    provider: str | None
    pages: dict[str, int]
    jobs: dict[str, int]
    knowledge_units: dict[str, int]
    awaiting_owner: dict[str, int]


def _admin(principal: Principal) -> Principal:
    require_roles(principal, *ADMIN_ROLES)
    return principal


@router.get("", response_model=PipelineStatus)
async def pipeline_status(principal: PrincipalDep, session: SessionDep) -> PipelineStatus:
    _admin(principal)
    current = state.current()
    counts: dict[str, Any] = {}
    for name, sql in COUNTS.items():
        rows = await session.execute(text(sql), {"u": principal.user_id})
        counts[name] = {str(r.k): int(r.n) for r in rows}
    return PipelineStatus(paused=current.reason, resume_at=current.until,
                          provider=current.provider, **counts)


@router.post("/pause", status_code=204)
async def pause(principal: PrincipalDep) -> Response:
    _admin(principal)
    state.set_manual(True)
    return Response(status_code=204)


@router.post("/resume", status_code=204)
async def resume(principal: PrincipalDep) -> Response:
    _admin(principal)
    state.set_manual(False)
    return Response(status_code=204)


@router.post("/approve", status_code=202)
async def approve(principal: PrincipalDep) -> dict[str, str]:
    """The owner's explicit OK: the worker redoes the saved items on Opus 5.5 high."""
    _admin(principal)
    _send("radbrain.approve_escalations", principal.tenant_id, principal.user_id)
    return {"status": "queued"}


@router.post("/dismiss")
async def dismiss(principal: PrincipalDep, session: SessionDep) -> dict[str, int]:
    _admin(principal)
    done = await session.execute(text(
        f"UPDATE model_escalations SET status = 'dismissed', resolved_at = now() "
        f"WHERE status = 'pending' AND source_id IN ({MINE})"),  # nosec B608 - constant SQL
        {"u": principal.user_id})
    return {"dismissed": int(getattr(done, "rowcount", 0) or 0)}


def _send(name: str, tenant_id: UUID, user_id: UUID) -> None:
    from apps.worker.app.celery_app import celery_app

    celery_app.send_task(name, args=[str(tenant_id), str(user_id)])
