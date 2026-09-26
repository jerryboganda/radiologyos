from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from apps.api.app.core.config import get_settings
from apps.api.app.db.session import get_system_session, tenant_context, tenant_session
from apps.api.app.preview.contracts import (
    PreviewBlockResponse,
    PreviewDeleteResponse,
    PreviewFigureResponse,
    PreviewJobResponse,
    PreviewPageResponse,
    PreviewSearchHit,
    PreviewSearchRequest,
    PreviewSearchResponse,
    PreviewSourceCreate,
    PreviewSourceResponse,
    PreviewStepResponse,
)
from apps.api.app.preview.service import (
    create_source,
    delete_source,
    find_job,
    find_source,
    get_preview_state,
    require_preview,
    search,
)
from apps.api.app.preview.state import PreviewJob, PreviewSource
from apps.api.app.schemas.common import Citation
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

preview_bearer = HTTPBearer(auto_error=False)


async def preview_principal_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(preview_bearer)],
    session: Annotated[AsyncSession, Depends(get_system_session)],
    x_user_id: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_role: Annotated[str | None, Header()] = None,
    x_radbrain_assertion: Annotated[str | None, Header()] = None,
) -> AsyncIterator[Principal]:
    from apps.api.app.main import principal_from_request

    principal = await principal_from_request(
        credentials=credentials,
        request=request,
        session=session,
        x_user_id=x_user_id,
        x_tenant_id=x_tenant_id,
        x_role=x_role,
        x_radbrain_assertion=x_radbrain_assertion or "",
    )
    if getattr(request.state, "requires_tenant_session", False):
        async with tenant_session(principal.tenant_id):
            yield principal
    else:
        with tenant_context(principal.tenant_id):
            yield principal


router = APIRouter(
    prefix=f"{get_settings().api_prefix}/preview",
    tags=["preview: non-release"],
    dependencies=[Depends(require_preview)],
)


def _source_response(source: PreviewSource) -> PreviewSourceResponse:
    return PreviewSourceResponse(
        id=str(source.id),
        title=source.title,
        kind=source.kind,
        status=source.status,
        page_count=source.page_count,
        figure_count=source.figure_count,
        chunk_count=source.chunk_count,
        created_at=source.created_at,
    )


def _job_response(job: PreviewJob) -> PreviewJobResponse:
    return PreviewJobResponse(
        id=str(job.id),
        source_id=str(job.source_id),
        status=job.status,
        steps=tuple(
            PreviewStepResponse(
                name=step.name,
                status=step.status,
                attempts=step.attempts,
                error_code=step.error_code,
            )
            for step in job.steps.values()
        ),
    )


@router.post(
    "/sources",
    response_model=tuple[PreviewSourceResponse, PreviewJobResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_preview_source(
    payload: PreviewSourceCreate,
    principal: Annotated[Principal, Depends(preview_principal_context)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> tuple[PreviewSourceResponse, PreviewJobResponse]:
    key = (
        idempotency_key
        or hashlib.sha256(
            f"{principal.tenant_id}:{payload.title}:{payload.content}".encode()
        ).hexdigest()
    )
    source, job = create_source(
        principal.tenant_id,
        principal.user_id,
        payload.title,
        payload.kind,
        payload.content,
        key,
    )
    return _source_response(source), _job_response(job)


@router.get("/sources", response_model=tuple[PreviewSourceResponse, ...])
def list_preview_sources(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> tuple[PreviewSourceResponse, ...]:
    sources = get_preview_state().sources(principal.tenant_id)
    return tuple(
        _source_response(source) for source in sources if source.owner_id == principal.user_id
    )


@router.get("/sources/{source_id}", response_model=PreviewSourceResponse)
def get_preview_source(
    source_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewSourceResponse:
    source = find_source(principal.tenant_id, source_id)
    if source.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="source not found")
    return _source_response(source)


@router.get("/sources/{source_id}/pages/{page_no}", response_model=PreviewPageResponse)
def get_preview_page(
    source_id: UUID,
    page_no: int,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewPageResponse:
    source = find_source(principal.tenant_id, source_id)
    if source.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="source not found")
    state = get_preview_state()
    page = state.page(principal.tenant_id, source_id, page_no)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    blocks = state.page_blocks(principal.tenant_id, source_id, page_no)
    figures = [
        figure
        for figure in state.source_figures(principal.tenant_id, source_id)
        if figure.page_no == page_no
    ]
    return PreviewPageResponse(
        page_no=page.page_no,
        width=page.width,
        height=page.height,
        image_key=page.image_key,
        blocks=tuple(
            PreviewBlockResponse(
                id=str(block.id),
                page_no=block.page_no,
                block_type=block.block_type,
                text=block.text,
                bbox=block.bbox,
                heading_path=block.heading_path,
            )
            for block in blocks
        ),
        figures=tuple(
            PreviewFigureResponse(
                id=str(figure.id),
                page_no=figure.page_no,
                caption=figure.caption,
                modality=figure.modality,
                image_key=figure.image_key,
            )
            for figure in figures
        ),
    )


@router.delete(
    "/sources/{source_id}",
    response_model=PreviewDeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def remove_preview_source(
    source_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewDeleteResponse:
    delete_source(principal.tenant_id, principal.user_id, source_id)
    return PreviewDeleteResponse(status="deleted", source_id=str(source_id))


@router.get("/jobs/{job_id}", response_model=PreviewJobResponse)
def get_preview_job(
    job_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewJobResponse:
    job = find_job(principal.tenant_id, job_id)
    if job.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_response(job)


@router.post("/search", response_model=PreviewSearchResponse)
def search_preview(
    payload: PreviewSearchRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewSearchResponse:
    chunks, figures = search(principal.tenant_id, payload.query, payload.limit)
    state = get_preview_state()
    visible_sources = {
        source.id
        for source in state.sources(principal.tenant_id)
        if source.owner_id == principal.user_id
    }
    visible_chunks = [item for item in chunks if item[0].source_id in visible_sources]
    visible_figures = [figure for figure in figures if figure.source_id in visible_sources]
    return PreviewSearchResponse(
        query=payload.query,
        chunks=tuple(
            PreviewSearchHit(
                text=chunk.text,
                score=score,
                citation=Citation(
                    source_id=str(chunk.source_id),
                    page_no=chunk.page_no,
                    block_id=str(chunk.block_start),
                    bbox=[0.0, 0.0, 0.0, 0.0],
                ),
            )
            for chunk, score in visible_chunks
        ),
        figures=tuple(
            PreviewFigureResponse(
                id=str(figure.id),
                page_no=figure.page_no,
                caption=figure.caption,
                modality=figure.modality,
                image_key=figure.image_key,
            )
            for figure in visible_figures
        ),
    )
