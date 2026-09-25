from __future__ import annotations

from uuid import UUID

from apps.api.app.core.config import get_settings
from apps.api.app.preview.library import ingest_source, search_chunks, search_figures
from apps.api.app.preview.state import (
    PreviewAudit,
    PreviewChunk,
    PreviewFigure,
    PreviewJob,
    PreviewSource,
    PreviewState,
)
from fastapi import HTTPException

_state = PreviewState()


def get_preview_state() -> PreviewState:
    return _state


def reset_preview_state() -> None:
    _state.reset()


def require_preview() -> None:
    if not get_settings().preview_enabled:
        raise HTTPException(status_code=404, detail="preview mode is disabled")


def create_source(
    tenant_id: UUID,
    owner_id: UUID,
    title: str,
    kind: str,
    content: str,
    idempotency_key: str,
) -> tuple[PreviewSource, PreviewJob]:
    try:
        return ingest_source(_state, tenant_id, owner_id, title, kind, content, idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def find_source(tenant_id: UUID, source_id: UUID) -> PreviewSource:
    source = _state.source(tenant_id, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


def find_job(tenant_id: UUID, job_id: UUID) -> PreviewJob:
    job = _state.job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def search(
    tenant_id: UUID, query: str, limit: int
) -> tuple[list[tuple[PreviewChunk, float]], list[PreviewFigure]]:
    return search_chunks(_state, tenant_id, query, limit), search_figures(
        _state, tenant_id, query, limit
    )


def delete_source(tenant_id: UUID, owner_id: UUID, source_id: UUID) -> None:
    source = find_source(tenant_id, source_id)
    if source.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="source not found")
    if not _state.soft_delete_source(tenant_id, source_id, _state.now()):
        raise HTTPException(status_code=404, detail="source not found")
    _state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="source.deleted",
            target_type="source",
            target_id=str(source_id),
            created_at=_state.now(),
        )
    )
