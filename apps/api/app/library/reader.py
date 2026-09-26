"""Page reader: blocks, figures, and authenticated image paths.

Object storage is private and reachable only inside the platform network, so
images are streamed through authenticated API routes rather than presigned.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.library import storage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def read_page(
    session: AsyncSession,
    user_id: UUID,
    source_id: UUID,
    page_no: int,
) -> dict[str, Any] | None:
    page = (
        await session.execute(
            text(
                """
                SELECT p.page_no, p.width, p.height, p.image_key, p.text_origin,
                       p.vision_status, s.title, s.page_count
                FROM source_pages p JOIN sources s ON s.id = p.source_id
                WHERE p.source_id = :s AND p.page_no = :p
                  AND s.uploaded_by = :u AND s.deleted_at IS NULL
                """
            ),
            {"s": source_id, "p": page_no, "u": user_id},
        )
    ).mappings().first()
    if page is None:
        return None
    blocks = await session.execute(
        text(
            "SELECT block_no, kind, text, bbox, origin FROM source_blocks "
            "WHERE source_id = :s AND page_no = :p ORDER BY block_no"
        ),
        {"s": source_id, "p": page_no},
    )
    figures = await session.execute(
        text(
            "SELECT id, figure_no, bbox, image_key, caption, description, modality, anatomy, "
            "findings FROM figures WHERE source_id = :s AND page_no = :p ORDER BY figure_no"
        ),
        {"s": source_id, "p": page_no},
    )
    return {
        "source_id": source_id,
        "title": page["title"],
        "page_no": page["page_no"],
        "page_count": page["page_count"],
        "width": page["width"],
        "height": page["height"],
        "text_origin": page["text_origin"],
        "vision_status": page["vision_status"],
        "image_path": f"/v1/library/sources/{source_id}/pages/{page_no}/image"
        if page["image_key"] else None,
        "blocks": [dict(b) for b in blocks.mappings()],
        "figures": [
            {**{k: v for k, v in dict(f).items() if k != "image_key"},
             "image_path": f"/v1/library/figures/{f['id']}/image" if f["image_key"] else None}
            for f in figures.mappings()
        ],
    }



async def image_key_for_page(
    session: AsyncSession, user_id: UUID, source_id: UUID, page_no: int
) -> str | None:
    value = (
        await session.execute(
            text(
                "SELECT p.image_key FROM source_pages p JOIN sources s ON s.id = p.source_id "
                "WHERE p.source_id = :s AND p.page_no = :p AND s.uploaded_by = :u "
                "AND s.deleted_at IS NULL"
            ),
            {"s": source_id, "p": page_no, "u": user_id},
        )
    ).scalar_one_or_none()
    return str(value) if value else None


async def image_key_for_figure(
    session: AsyncSession, user_id: UUID, figure_id: UUID
) -> str | None:
    value = (
        await session.execute(
            text(
                "SELECT f.image_key FROM figures f JOIN sources s ON s.id = f.source_id "
                "WHERE f.id = :f AND s.uploaded_by = :u AND s.deleted_at IS NULL"
            ),
            {"f": figure_id, "u": user_id},
        )
    ).scalar_one_or_none()
    return str(value) if value else None


def fetch_image(store: storage.ObjectStore, tenant_id: UUID, key: str) -> bytes:
    storage.require_tenant_key(tenant_id, key)
    return store.get(key)
