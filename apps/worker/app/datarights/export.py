"""Build one user's account export ZIP (ADR 0018).

Layout: ``data/<table>.json`` (the user's own rows of every table in the
registry, embeddings included), ``notes/cards.md`` and ``notes/claims.md``
(readable, cited), ``files/<source>/`` (original uploads), ``figures/<source>/``
(figure crops), ``manifest.json`` (counts), and ``README.md``. The ZIP is
written to a temporary file, uploaded to ``tenants/<tenant>/exports/<job>.zip``
and removed locally. Re-running rebuilds the same key, so the job is idempotent.
"""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from apps.worker.app.datarights import jobs, notes, registry
from apps.worker.app.ingest.db import tenant_tx
from packages.library import storage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FORMAT = "radbrain-export/1"
README = """# radbrain account export

This archive holds everything radbrain stores for your account:

- `data/<table>.json` - your rows in every table, as JSON (embeddings included);
- `notes/cards.md`, `notes/claims.md` - your cards and extracted claims, each
  with its source and page citation;
- `files/<source-id>/` - the original files you uploaded;
- `figures/<source-id>/` - figure crops extracted from your sources;
- `manifest.json` - row and file counts.

The download link expires 7 days after the export was built.
"""
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(name: str | None, fallback: str) -> str:
    cleaned = _UNSAFE.sub("_", (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip(" .")
    return cleaned[-120:] or fallback


async def run_export(deps: jobs.DataDeps, tenant_id: UUID, job_id: UUID) -> str:
    async with tenant_tx(deps.engine, tenant_id) as session:
        job = await jobs.load(session, job_id, "export")
        if job is None:
            return "missing"
        if job["status"] == "succeeded":
            return "done"
        user_id = UUID(str(job["user_id"]))
        if await jobs.account_deleting(session, user_id):
            await session.execute(
                text("UPDATE data_jobs SET status = 'failed', error_code = 'account_deleting', "
                     "finished_at = now() WHERE id = :id"),
                {"id": job_id},
            )
            return "cancelled"
        await jobs.start(session, job_id)
        await jobs.set_step(session, job_id, "building")
    key = storage.export_key(tenant_id, job_id)
    with tempfile.TemporaryDirectory(prefix="radbrain-export-") as tmp:
        path = Path(tmp) / "export.zip"
        counts = await write_zip(deps, tenant_id, user_id, job_id, path)
        with path.open("rb") as handle:
            deps.store.put_file(key, handle, "application/zip")
        size = path.stat().st_size
    async with tenant_tx(deps.engine, tenant_id) as session:
        kept = await jobs.finish(session, job_id, counts, key, size)
    if not kept:  # erased while building: never leave the archive behind
        deps.store.delete_prefix(key)
        return "cancelled"
    return "succeeded"


async def write_zip(
    deps: jobs.DataDeps, tenant_id: UUID, user_id: UUID, job_id: UUID, path: Path
) -> dict[str, Any]:
    tables: dict[str, int] = {}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        async with tenant_tx(deps.engine, tenant_id) as session:
            for item in registry.OWNED:
                tables[item.table] = await _write_table(session, zf, item, user_id)
            zf.writestr("notes/cards.md", await notes.cards_markdown(session, user_id))
            zf.writestr("notes/claims.md", await notes.claims_markdown(session, user_id))
            files = await _object_files(session, user_id)
        copied, missing = _copy_objects(deps.store, zf, tenant_id, files)
        counts = {"tables": tables, "files": copied, "missing_files": missing}
        manifest = {"format": FORMAT, "job_id": str(job_id), "user_id": str(user_id),
                    "generated_at": datetime.now(UTC).isoformat(), **counts}
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        zf.writestr("README.md", README)
    return counts


async def _write_table(
    session: AsyncSession, zf: zipfile.ZipFile, item: registry.Owned, user_id: UUID
) -> int:
    count = 0
    with zf.open(f"data/{item.table}.json", "w", force_zip64=True) as handle:
        handle.write(b"[")
        result = await session.stream(text(registry.select_sql(item)), {"u": user_id})
        async for row in result:
            handle.write((b",\n" if count else b"\n") + str(row[0]).encode("utf-8"))
            count += 1
        handle.write(b"\n]\n")
    return count


async def _object_files(session: AsyncSession, user_id: UUID) -> list[tuple[str, str]]:
    """(archive name, object key) for originals and figure crops."""
    originals = await session.execute(
        text(
            "SELECT id, storage_key, original_filename FROM sources "
            "WHERE uploaded_by = :u AND storage_key IS NOT NULL ORDER BY created_at"
        ),
        {"u": user_id},
    )
    files = [
        (f"files/{row['id']}/{safe_name(row['original_filename'], 'original')}",
         str(row["storage_key"]))
        for row in originals.mappings()
    ]
    crops = await session.execute(
        text(
            f"SELECT source_id, page_no, figure_no, image_key FROM figures "  # nosec B608 - constant subquery from the registry
            f"WHERE image_key IS NOT NULL AND source_id IN ({registry.MY_SOURCES}) "
            f"ORDER BY source_id, page_no, figure_no"
        ),
        {"u": user_id},
    )
    files += [
        (f"figures/{row['source_id']}/{row['page_no']:05d}-{row['figure_no']:03d}.png",
         str(row["image_key"]))
        for row in crops.mappings()
    ]
    return files


def _is_missing(exc: Exception) -> bool:
    if isinstance(exc, KeyError):
        return True
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code in {"NoSuchKey", "404", "NotFound"}


def _copy_objects(
    store: storage.ObjectStore, zf: zipfile.ZipFile, tenant_id: UUID,
    files: list[tuple[str, str]],
) -> tuple[int, int]:
    """Stream each object into the archive; a vanished object is counted, not fatal."""
    copied = missing = 0
    for arcname, key in files:
        storage.require_tenant_key(tenant_id, key)
        try:
            chunks = store.iter_chunks(key)
            first = next(chunks, b"")
        except Exception as exc:
            if not _is_missing(exc):
                raise
            missing += 1
            continue
        with zf.open(arcname, "w", force_zip64=True) as dest:
            dest.write(first)
            for chunk in chunks:
                dest.write(chunk)
        copied += 1
    return copied, missing
