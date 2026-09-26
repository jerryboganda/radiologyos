"""Library API: upload, list, detail, page reader, images, search, delete."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.core.config import get_settings
from apps.api.app.library import reader, search, service
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from packages.library.formats import UnsupportedUpload
from packages.library.storage import ObjectStore, S3ObjectStore
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/library", tags=["library"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    s = get_settings()
    return S3ObjectStore(s.s3_endpoint, s.s3_bucket, s.s3_access_key, s.s3_secret_key,
                         s.s3_region)


def enqueue_ingest(tenant_id: UUID, job_id: UUID) -> None:
    from apps.worker.app.celery_app import celery_app

    celery_app.send_task("radbrain.ingest_source", args=[str(tenant_id), str(job_id)])


class UploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    job_id: UUID | None
    duplicate: bool


class SourceSummary(BaseModel):
    id: UUID
    title: str
    kind: str
    status: str
    page_count: int | None
    byte_size: int | None
    created_at: datetime
    pages_parsed: int = 0
    figure_count: int = 0


class StepStatus(BaseModel):
    step: str
    status: str
    attempts: int
    error_code: str | None
    output_ref: str | None


class SourceDetail(BaseModel):
    id: UUID
    title: str
    kind: str
    status: str
    page_count: int | None
    byte_size: int | None
    created_at: datetime
    steps: list[StepStatus]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=30)


class Citation(BaseModel):
    source_id: UUID
    source_title: str
    page_from: int
    page_to: int
    block_refs: list[dict[str, int]]


class SearchHit(BaseModel):
    chunk_id: UUID
    heading: str
    text: str
    score: float
    citation: Citation


class FigureHit(BaseModel):
    figure_id: UUID
    source_id: UUID
    source_title: str
    page_no: int
    caption: str
    description: str
    modality: str
    anatomy: str
    image_path: str | None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    figures: list[FigureHit]
    dense: bool


@router.post("/sources", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_source(
    principal: PrincipalDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    settings = get_settings()
    try:
        created = await service.create_source(
            session, get_store(), principal, file.file, file.filename or "upload",
            settings.max_upload_bytes, settings.pipeline_version, title,
        )
    except UnsupportedUpload as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except service.UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if created["job_id"] is not None:
        enqueue_ingest(principal.tenant_id, created["job_id"])
    return UploadResponse(**created)


@router.get("/sources", response_model=list[SourceSummary])
async def list_sources(principal: PrincipalDep, session: SessionDep) -> list[SourceSummary]:
    return [SourceSummary(**row) for row in await service.list_sources(session, principal)]


@router.get("/sources/{source_id}", response_model=SourceDetail)
async def source_detail(
    source_id: UUID, principal: PrincipalDep, session: SessionDep
) -> SourceDetail:
    found = await service.get_source(session, principal, source_id)
    if found is None:
        raise HTTPException(status_code=404, detail="source not found")
    return SourceDetail(**{k: v for k, v in found.items() if k != "storage_key"})


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: UUID, principal: PrincipalDep, session: SessionDep) -> None:
    if not await service.delete_source(session, get_store(), principal, source_id):
        raise HTTPException(status_code=404, detail="source not found")


@router.get("/sources/{source_id}/pages/{page_no}")
async def read_page(
    source_id: UUID, page_no: int, principal: PrincipalDep, session: SessionDep
) -> dict[str, Any]:
    page = await reader.read_page(session, principal.user_id, source_id, page_no)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return page


@router.get("/sources/{source_id}/pages/{page_no}/image")
async def page_image(
    source_id: UUID, page_no: int, principal: PrincipalDep, session: SessionDep
) -> Response:
    key = await reader.image_key_for_page(session, principal.user_id, source_id, page_no)
    return _image(principal, key)


@router.get("/figures/{figure_id}/image")
async def figure_image(figure_id: UUID, principal: PrincipalDep, session: SessionDep) -> Response:
    key = await reader.image_key_for_figure(session, principal.user_id, figure_id)
    return _image(principal, key)


def _image(principal: Principal, key: str | None) -> Response:
    if key is None:
        raise HTTPException(status_code=404, detail="image not found")
    data = reader.fetch_image(get_store(), principal.tenant_id, key)
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.post("/search", response_model=SearchResponse)
async def search_library(
    body: SearchRequest, principal: PrincipalDep, session: SessionDep
) -> SearchResponse:
    vector = await run_in_threadpool(query_vector, body.query)
    hits = await search.hybrid_search(session, principal.user_id, body.query, vector, body.limit)
    figures = await search.search_figures(session, principal.user_id, body.query)
    return SearchResponse(
        query=body.query,
        dense=vector is not None,
        hits=[
            SearchHit(
                chunk_id=h["id"], heading=h["heading"], text=h["text"], score=h["score"],
                citation=Citation(source_id=h["source_id"], source_title=h["source_title"],
                                  page_from=h["page_from"], page_to=h["page_to"],
                                  block_refs=h["block_refs"]),
            )
            for h in hits
        ],
        figures=[
            FigureHit(figure_id=f["id"], source_id=f["source_id"],
                      source_title=f["source_title"], page_no=f["page_no"],
                      caption=f["caption"], description=f["description"],
                      modality=f["modality"], anatomy=f["anatomy"],
                      image_path=f"/v1/library/figures/{f['id']}/image"
                      if f["image_key"] else None)
            for f in figures
        ],
    )


def query_vector(query: str) -> list[float] | None:
    from packages.models.embeddings import EmbeddingError, VoyageEmbedder
    from packages.models.gateway import routing_config

    config = routing_config().embeddings
    if config is None:
        return None
    embedder = VoyageEmbedder(config, timeout_s=10.0)
    if not embedder.available():
        return None
    try:
        return embedder.embed([query], "query")[0]
    except EmbeddingError:
        return None
