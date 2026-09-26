"""Tutor image upload and download (ADR 0025).

``POST /v1/tutor/images`` accepts one PNG, JPEG, or WebP image of at most
20 MB (content-sniffed; DICOM refused), re-encodes it without metadata, stores
it privately under the caller's tenant and user prefix, and returns its id for
``POST /v1/tutor/ask``. ``GET /v1/tutor/images/{id}`` streams it back to its
owner only, privately cacheable for five minutes, so the browser never holds a
storage URL at all. Shares the tutor router's dependencies, so test overrides
apply to both.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from apps.api.app.api.tutor import UPLOAD_LIMIT, PrincipalDep, SessionDep, StoreDep
from apps.api.app.observability import logger
from apps.api.app.tutor import images
from apps.api.app.tutor.contracts import ImageUploadResponse
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from packages.library.storage import tutor_image_key
from packages.tutor.image import MAX_IMAGE_BYTES, ImageRejected, clean_image

router = APIRouter(prefix="/v1/tutor", tags=["tutor"])


@router.post("/images", response_model=ImageUploadResponse,
             status_code=status.HTTP_201_CREATED, dependencies=[UPLOAD_LIMIT])
async def upload_image(
    principal: PrincipalDep, session: SessionDep, store: StoreDep,
    file: Annotated[UploadFile, File()],
) -> ImageUploadResponse:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    try:
        clean = await run_in_threadpool(clean_image, data)
    except ImageRejected as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    image_id = uuid4()
    key = tutor_image_key(principal.tenant_id, principal.user_id, image_id, clean.extension)
    await images.insert_image(session, principal.tenant_id, principal.user_id, image_id, key,
                              clean)
    await run_in_threadpool(store.put, key, clean.data, clean.content_type)
    await session.commit()
    logger.info("tutor_image_uploaded", extra={"image_id": str(image_id),
                                               "bytes": len(clean.data)})
    return ImageUploadResponse(image_id=image_id, content_type=clean.content_type,
                               byte_size=len(clean.data), width=clean.width,
                               height=clean.height)


@router.get("/images/{image_id}")
async def image_bytes(
    image_id: UUID, principal: PrincipalDep, session: SessionDep, store: StoreDep
) -> Response:
    row = await images.get_image(session, principal.user_id, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="image not found")
    data = await run_in_threadpool(images.fetch_bytes, store, principal.tenant_id,
                                   str(row["storage_key"]))
    return Response(content=data, media_type=str(row["content_type"]),
                    headers={"Cache-Control": "private, max-age=300",
                             "X-Content-Type-Options": "nosniff"})
