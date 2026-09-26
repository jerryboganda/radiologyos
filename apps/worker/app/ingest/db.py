"""Tenant-scoped database access for the ingestion worker.

Every unit of work opens its own transaction, sets ``app.tenant_id`` with
``set_config(..., true)`` (transaction-local), and runs as the RLS-bound
runtime role, so the worker can never read or write another tenant's rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from packages.observability import metrics
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine


def make_engine() -> AsyncEngine:
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://localhost/radbrain")
    return create_async_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)


@asynccontextmanager
async def tenant_tx(engine: AsyncEngine, tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        yield session


async def load_source(session: AsyncSession, source_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, kind, storage_key, title, status, page_count "
                "FROM sources WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": source_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def set_source_status(
    session: AsyncSession, source_id: UUID, status: str, page_count: int | None = None
) -> None:
    await session.execute(
        text(
            "UPDATE sources SET status = :status, "
            "page_count = COALESCE(:page_count, page_count) WHERE id = :id"
        ),
        {"id": source_id, "status": status, "page_count": page_count},
    )


async def step_status(session: AsyncSession, job_id: UUID, step: str) -> str | None:
    value = (
        await session.execute(
            text("SELECT status FROM job_steps WHERE job_id = :job AND step = :step"),
            {"job": job_id, "step": step},
        )
    ).scalar_one_or_none()
    return str(value) if value is not None else None


async def mark_step(
    session: AsyncSession,
    job: dict[str, Any],
    step: str,
    status: str,
    error_code: str | None = None,
    output_ref: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO job_steps
                (tenant_id, job_id, entity_id, step, pipeline_version, status,
                 attempts, error_code, output_ref)
            VALUES (:tenant, :job, :entity, :step, :version, :status,
                    CASE WHEN :status = 'running' THEN 1 ELSE 0 END, :error, :output)
            ON CONFLICT (tenant_id, job_id, step, pipeline_version) DO UPDATE SET
                status = EXCLUDED.status,
                attempts = job_steps.attempts
                    + CASE WHEN EXCLUDED.status = 'running' THEN 1 ELSE 0 END,
                error_code = EXCLUDED.error_code,
                output_ref = COALESCE(EXCLUDED.output_ref, job_steps.output_ref)
            """
        ),
        {
            "tenant": job["tenant_id"],
            "job": job["id"],
            "entity": job["entity_id"],
            "step": step,
            "version": job["pipeline_version"],
            "status": status,
            "error": error_code,
            "output": output_ref,
        },
    )
    if status != "running":  # outcome counters for /metrics (ADR 0032); ids never labelled
        metrics.shared().inc("radbrain_job_steps_total", {"step": step, "status": status})


async def set_job_status(
    session: AsyncSession, job_id: UUID, status: str, error_code: str | None = None
) -> None:
    await session.execute(
        text(
            "UPDATE jobs SET status = :status, error_code = :error, "
            "attempts = attempts + CASE WHEN :status = 'running' THEN 1 ELSE 0 END "
            "WHERE id = :id"
        ),
        {"id": job_id, "status": status, "error": error_code},
    )


async def load_job(session: AsyncSession, job_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, tenant_id, entity_id, pipeline_version, status "
                "FROM jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def upsert_page(session: AsyncSession, values: dict[str, Any]) -> None:
    await session.execute(
        text(
            """
            INSERT INTO source_pages
                (tenant_id, source_id, page_no, width, height, image_key, native_text, text_origin)
            VALUES (:tenant_id, :source_id, :page_no, :width, :height, :image_key,
                    :native_text, :text_origin)
            ON CONFLICT (tenant_id, source_id, page_no) DO UPDATE SET
                width = EXCLUDED.width, height = EXCLUDED.height,
                image_key = EXCLUDED.image_key, native_text = EXCLUDED.native_text
            """
        ),
        values,
    )


async def replace_blocks(
    session: AsyncSession,
    tenant_id: UUID,
    source_id: UUID,
    page_no: int,
    blocks: Sequence[dict[str, Any]],
) -> None:
    await session.execute(
        text("DELETE FROM source_blocks WHERE source_id = :s AND page_no = :p"),
        {"s": source_id, "p": page_no},
    )
    for block in blocks:
        await session.execute(
            text(
                "INSERT INTO source_blocks (tenant_id, source_id, page_no, block_no, kind, "
                "text, bbox, origin) VALUES (:t, :s, :p, :n, :kind, :text, :bbox, :origin)"
            ),
            {
                "t": tenant_id, "s": source_id, "p": page_no, "n": block["block_no"],
                "kind": block["kind"], "text": block["text"], "bbox": list(block["bbox"]),
                "origin": block["origin"],
            },
        )


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
