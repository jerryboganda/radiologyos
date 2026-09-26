"""Data rights: account export (durable ZIP job) and account deletion (ADR 0018)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.app.api.library import get_store
from apps.api.app.datarights import service
from apps.api.app.ops.ratelimit import rate_limit
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/me", tags=["data-rights"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]


class DataJob(BaseModel):
    id: UUID
    kind: Literal["export", "delete"]
    status: Literal["queued", "running", "succeeded", "failed"]
    step: str
    byte_size: int | None
    detail: dict[str, Any]
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
    download_path: str | None = None


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(
        min_length=1, max_length=100,
        description=f'Type "{service.DELETE_CONFIRMATION}" to confirm.',
    )


def enqueue(kind: str, tenant_id: UUID, job_id: UUID) -> None:
    from apps.worker.app.celery_app import celery_app

    name = "radbrain.data_export" if kind == "export" else "radbrain.data_delete"
    celery_app.send_task(name, args=[str(tenant_id), str(job_id)])


def _job(row: dict[str, Any]) -> DataJob:
    fields = {k: v for k, v in row.items() if k in DataJob.model_fields}
    fields["detail"] = service.public_detail(row.get("detail"))
    job = DataJob(**fields)
    if job.kind == "export" and job.status == "succeeded":
        job.download_path = f"/v1/me/exports/{job.id}/download"
    return job


@router.post("/export", response_model=DataJob, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(rate_limit("export", principal_context))])
async def request_export(principal: PrincipalDep, session: SessionDep) -> DataJob:
    """Queue a ZIP of everything stored for the caller; re-requests return the active job."""
    try:
        row, _ = await service.request_job(session, principal, "export")
    except service.AccountDeleting as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Re-sending an active job is safe: the worker is idempotent and resumable.
    enqueue("export", principal.tenant_id, row["id"])
    return _job(row)


@router.get("/exports", response_model=list[DataJob])
async def list_exports(principal: PrincipalDep, session: SessionDep) -> list[DataJob]:
    return [_job(row) for row in await service.list_exports(session, principal.user_id)]


@router.get(
    "/exports/{job_id}/download",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}}, 404: {"description": "Not found"}},
)
async def download_export(
    job_id: UUID, principal: PrincipalDep, session: SessionDep
) -> StreamingResponse:
    """Stream the caller's own export through the API (no public URL), audited."""
    found = await service.export_for_download(session, principal, job_id)
    if found is None:
        raise HTTPException(status_code=404, detail="export not found or expired")
    key = str(found["object_key"])
    if not key.startswith(f"tenants/{principal.tenant_id}/exports/"):
        raise HTTPException(status_code=404, detail="export not found or expired")
    stamp = found["finished_at"].strftime("%Y%m%d") if found["finished_at"] else "export"
    headers = {
        "Content-Disposition": f'attachment; filename="radbrain-export-{stamp}.zip"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if found["byte_size"] is not None:
        headers["Content-Length"] = str(found["byte_size"])
    return StreamingResponse(get_store().iter_chunks(key), media_type="application/zip",
                             headers=headers)


@router.delete("", response_model=DataJob, status_code=status.HTTP_202_ACCEPTED)
async def delete_account(
    body: DeleteAccountRequest, principal: PrincipalDep, session: SessionDep
) -> DataJob:
    """Queue erasure of the caller's account and everything derived from it."""
    if body.confirmation.strip().lower() != service.DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=422,
            detail=f'type "{service.DELETE_CONFIRMATION}" to confirm account deletion',
        )
    row, _ = await service.request_job(session, principal, "delete")
    enqueue("delete", principal.tenant_id, row["id"])
    return _job(row)
