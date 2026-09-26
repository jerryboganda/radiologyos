"""Library operations: upload, list, detail, page view, delete.

Every query runs in the caller's transaction-local tenant session (RLS), and is
additionally scoped to the uploading user, so personal uploads are never
visible to another member of the same tenant.
"""

from __future__ import annotations

import hashlib
import tempfile
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from apps.api.app.security.principal import Principal
from packages.library import storage
from packages.library.formats import DetectedFormat, UnsupportedUpload, clean_title, detect_format
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CHUNK = 1024 * 1024


class UploadTooLarge(ValueError):
    pass


def spool_upload(stream: BinaryIO, limit: int) -> tuple[BinaryIO, str, int, bytes]:
    """Copy an upload to a temp file, hashing it; return (file, sha256, size, head)."""
    digest = hashlib.sha256()
    spooled = tempfile.SpooledTemporaryFile(max_size=8 * CHUNK)  # noqa: SIM115
    size = 0
    head = b""
    while chunk := stream.read(CHUNK):
        size += len(chunk)
        if size > limit:
            spooled.close()
            raise UploadTooLarge("file exceeds the upload limit")
        if len(head) < 65536:
            head += chunk[: 65536 - len(head)]
        digest.update(chunk)
        spooled.write(chunk)
    spooled.seek(0)
    return spooled, digest.hexdigest(), size, head  # type: ignore[return-value]


async def find_duplicate(session: AsyncSession, sha256: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT id, title, status FROM sources WHERE sha256 = :h AND deleted_at IS NULL"),
            {"h": sha256},
        )
    ).mappings().first()
    return dict(row) if row else None


async def create_source(
    session: AsyncSession,
    store: storage.ObjectStore,
    principal: Principal,
    stream: BinaryIO,
    filename: str,
    limit: int,
    pipeline_version: int,
    title: str | None = None,
) -> dict[str, Any]:
    spooled, sha256, size, head = spool_upload(stream, limit)
    try:
        detected: DetectedFormat = detect_format(head, filename)
        duplicate = await find_duplicate(session, sha256)
        if duplicate is not None:
            return {"duplicate": True, "source_id": duplicate["id"], "job_id": None}
        source_id, job_id = uuid4(), uuid4()
        key = storage.original_key(principal.tenant_id, source_id, detected.extension)
        store.put_file(key, spooled, detected.mime_type)
    finally:
        spooled.close()
    await _insert_rows(session, principal, source_id, job_id, key, sha256, size, detected,
                       title or clean_title(filename), filename, pipeline_version)
    await session.commit()
    return {"duplicate": False, "source_id": source_id, "job_id": job_id}


async def _insert_rows(
    session: AsyncSession, principal: Principal, source_id: UUID, job_id: UUID, key: str,
    sha256: str, size: int, detected: DetectedFormat, title: str, filename: str, version: int,
) -> None:
    await session.execute(
        text(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
            "title, original_filename, byte_size, mime_type) VALUES (:id, :t, :u, :kind, "
            "'private', :sha, :key, :title, :fname, :size, :mime)"
        ),
        {"id": source_id, "t": principal.tenant_id, "u": principal.user_id,
         "kind": detected.kind.value, "sha": sha256, "key": key, "title": title[:500],
         "fname": filename[-500:], "size": size, "mime": detected.mime_type},
    )
    await session.execute(
        text(
            "INSERT INTO jobs (id, tenant_id, entity_id, kind, idempotency_key, pipeline_version) "
            "VALUES (:id, :t, :s, 'ingest_source', :key, :v)"
        ),
        {"id": job_id, "t": principal.tenant_id, "s": source_id,
         "key": f"ingest:{source_id}:v{version}", "v": version},
    )
    await audit(session, principal, "source.uploaded", "source", str(source_id),
                {"sha256": sha256, "bytes": size, "kind": detected.kind.value})


async def audit(
    session: AsyncSession, principal: Principal, action: str, target_type: str,
    target_id: str, metadata: dict[str, Any] | None = None,
) -> None:
    import json

    await session.execute(
        text(
            "INSERT INTO audit_log (tenant_id, actor_user_id, action, target_type, target_id, "
            "metadata) VALUES (:t, :u, :a, :tt, :tid, CAST(:m AS jsonb))"
        ),
        {"t": principal.tenant_id, "u": principal.user_id, "a": action, "tt": target_type,
         "tid": target_id, "m": json.dumps(metadata or {})},
    )


async def list_sources(session: AsyncSession, principal: Principal) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT s.id, s.title, s.kind, s.status, s.page_count, s.byte_size, s.created_at,
                   (SELECT count(*) FROM source_pages p WHERE p.source_id = s.id
                      AND p.vision_status = 'done') AS pages_parsed,
                   (SELECT count(*) FROM figures f WHERE f.source_id = s.id) AS figure_count
            FROM sources s
            WHERE s.uploaded_by = :u AND s.deleted_at IS NULL
            ORDER BY s.created_at DESC
            """
        ),
        {"u": principal.user_id},
    )
    return [dict(row) for row in rows.mappings()]


async def get_source(
    session: AsyncSession, principal: Principal, source_id: UUID
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, title, kind, status, page_count, byte_size, created_at, storage_key "
                "FROM sources WHERE id = :id AND uploaded_by = :u AND deleted_at IS NULL"
            ),
            {"id": source_id, "u": principal.user_id},
        )
    ).mappings().first()
    if row is None:
        return None
    steps = await session.execute(
        text(
            "SELECT js.step, js.status, js.attempts, js.error_code, js.output_ref "
            "FROM job_steps js JOIN jobs j ON j.id = js.job_id "
            "WHERE j.entity_id = :id ORDER BY js.created_at"
        ),
        {"id": source_id},
    )
    return {**dict(row), "steps": [dict(s) for s in steps.mappings()]}


class SourceOnHold(PermissionError):
    """The source is under legal hold and must not be deleted."""


async def purge_source_rows(session: AsyncSession, source_id: UUID) -> None:
    """Delete one source and everything derived from it (no commit).

    Pages, blocks, figures, chunks (with embeddings), claims, mappings, cards,
    and knowledge runs cascade from ``sources``; jobs are keyed by entity, and
    concepts left with no claim and no edge are removed with the source. Shared
    by the per-source delete and the account-deletion job (ADR 0018).
    """
    concepts = (
        await session.execute(
            text(
                "SELECT concept_id FROM claims WHERE source_id = :id UNION "
                "SELECT from_concept FROM concept_edges WHERE source_id = :id UNION "
                "SELECT to_concept FROM concept_edges WHERE source_id = :id"
            ),
            {"id": source_id},
        )
    ).scalars().all()
    await session.execute(text("DELETE FROM jobs WHERE entity_id = :id"), {"id": source_id})
    await session.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})
    if concepts:
        await session.execute(
            text(
                "DELETE FROM concepts k WHERE k.id = ANY(:ids) "
                "AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.concept_id = k.id) "
                "AND NOT EXISTS (SELECT 1 FROM concept_edges e "
                "WHERE k.id IN (e.from_concept, e.to_concept))"
            ),
            {"ids": list(concepts)},
        )


async def delete_source(
    session: AsyncSession, store: storage.ObjectStore, principal: Principal, source_id: UUID
) -> bool:
    source = await get_source(session, principal, source_id)
    if source is None:
        return False
    held = (
        await session.execute(
            text("SELECT legal_hold FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).scalar_one()
    if held:
        raise SourceOnHold("source is under legal hold")
    # Objects first: a crash after this leaves rows that a retry deletes again,
    # never unreachable orphan objects.
    store.delete_prefix(storage.source_prefix(principal.tenant_id, source_id) + "/")
    await purge_source_rows(session, source_id)
    await audit(session, principal, "source.deleted", "source", str(source_id))
    await session.commit()
    return True


__all__ = ["SourceOnHold", "UnsupportedUpload", "UploadTooLarge", "create_source",
           "delete_source", "get_source", "list_sources", "purge_source_rows"]
