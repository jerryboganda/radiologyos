"""Persistence for images attached to tutor questions (ADR 0025).

Rows live in ``tutor_images`` (FORCE RLS) and every query is additionally
scoped to the uploading user, so another member of the tenant cannot read,
ask about, or download someone else's image. Bytes live in private object
storage under ``storage.tutor_image_prefix``; nothing here logs them.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from packages.library.parse_models import ImageCase
from packages.library.storage import ObjectStore, require_tenant_key
from packages.tutor.image import CleanImage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_image(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, image_id: UUID, key: str,
    image: CleanImage,
) -> None:
    await session.execute(
        text(
            "INSERT INTO tutor_images (id, tenant_id, user_id, storage_key, content_type, "
            "byte_size, width, height, sha256) VALUES (:id, :t, :u, :k, :ct, :n, :w, :h, :sha)"
        ),
        {"id": image_id, "t": tenant_id, "u": user_id, "k": key, "ct": image.content_type,
         "n": len(image.data), "w": image.width, "h": image.height, "sha": image.sha256},
    )


async def get_image(
    session: AsyncSession, user_id: UUID, image_id: UUID
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT id, storage_key, content_type, reading, reading_version "
                 "FROM tutor_images WHERE id = :id AND user_id = :u"),
            {"id": image_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def save_reading(
    session: AsyncSession, image_id: UUID, reading: ImageCase, version: str
) -> None:
    """Cache the vision reading so follow-ups about the same image cost no model call."""
    await session.execute(
        text("UPDATE tutor_images SET reading = CAST(:r AS jsonb), reading_version = :v "
             "WHERE id = :id"),
        {"id": image_id, "v": version,
         "r": json.dumps(reading.model_dump(mode="json"), ensure_ascii=False)},
    )


def fetch_bytes(store: ObjectStore, tenant_id: UUID, key: str) -> bytes:
    """Read an image object, refusing any key outside the caller's tenant prefix."""
    require_tenant_key(tenant_id, key)
    return store.get(key)


def stored_reading(value: Any) -> ImageCase | None:
    """A cached reading from jsonb (asyncpg may hand it over as text)."""
    if isinstance(value, str):
        value = json.loads(value)
    return ImageCase.model_validate(value) if isinstance(value, dict) else None
