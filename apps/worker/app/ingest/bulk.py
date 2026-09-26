"""Bulk import a directory into one user's library, server side.

Usage (inside the worker container, files mounted read-only):
    python -m apps.worker.app.ingest.bulk --subject <oidc-subject> --dir /import
    python -m apps.worker.app.ingest.bulk --subject <oidc-subject> --reprocess

Uses the same upload path as the API (content sniffing, DICOM refusal,
SHA-256 dedupe, tenant-prefixed keys, audit), so re-running is safe: files
already imported are skipped. ``--reprocess`` re-queues only the user's jobs that still have work,
which resumes pending steps such as the vision pass once the model token or
embedding key is configured. Only counts and ids are printed, never content.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from uuid import UUID

from apps.api.app.library import service
from apps.api.app.security.principal import Principal
from apps.worker.app.celery_app import celery_app
from apps.worker.app.ingest.db import make_engine
from apps.worker.app.ingest.runtime import object_store
from packages.library.formats import UnsupportedUpload
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SUFFIXES = {".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png", ".webp"}
LIMIT = int(os.environ.get("MAX_UPLOAD_BYTES", str(300 * 1024 * 1024)))


async def resolve(engine: AsyncEngine, subject: str) -> Principal:
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                text("SELECT user_id, tenant_id, role FROM app.resolve_memberships(:s)"),
                {"s": subject},
            )
        ).all()
    if len(rows) != 1:
        raise SystemExit("subject must have exactly one active membership")
    user_id, tenant_id, role = rows[0]
    return Principal(user_id=UUID(str(user_id)), tenant_id=UUID(str(tenant_id)), role=str(role))


async def tenant_session(engine: AsyncEngine, tenant_id: UUID) -> AsyncSession:
    session = AsyncSession(engine, expire_on_commit=False)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    return session


def enqueue(tenant_id: UUID, job_id: UUID) -> None:
    celery_app.send_task("radbrain.ingest_source", args=[str(tenant_id), str(job_id)])


async def import_dir(engine: AsyncEngine, principal: Principal, directory: Path) -> None:
    store = object_store()
    counts = {"imported": 0, "duplicate": 0, "rejected": 0}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        if path.suffix.lower() not in SUFFIXES:
            counts["rejected"] += 1
            continue
        session = await tenant_session(engine, principal.tenant_id)
        try:
            with path.open("rb") as stream:
                created = await service.create_source(
                    session, store, principal, stream, path.name, LIMIT, 1
                )
        except (UnsupportedUpload, service.UploadTooLarge):
            counts["rejected"] += 1
            continue
        finally:
            await session.close()
        if created["duplicate"]:
            counts["duplicate"] += 1
            continue
        enqueue(principal.tenant_id, created["job_id"])
        counts["imported"] += 1
        print(f"queued source={created['source_id']} job={created['job_id']}", flush=True)
    print(f"done {counts}", flush=True)


# Only jobs with real work left: never re-run (and re-pay for) finished sources.
REPROCESS_SQL = """
SELECT j.id FROM jobs j JOIN sources s ON s.id = j.entity_id
WHERE s.uploaded_by = :u AND s.deleted_at IS NULL AND j.kind = 'ingest_source' AND (
    j.status <> 'succeeded'
    OR EXISTS (SELECT 1 FROM source_pages p
               WHERE p.source_id = s.id AND p.vision_status = 'pending')
    OR EXISTS (SELECT 1 FROM chunks c WHERE c.source_id = s.id AND c.embedding IS NULL)
    OR EXISTS (SELECT 1 FROM figures f WHERE f.source_id = s.id AND f.embedding IS NULL
               AND length(f.caption || f.description) >= 20)
)
"""


async def reprocess(engine: AsyncEngine, principal: Principal) -> None:
    session = await tenant_session(engine, principal.tenant_id)
    try:
        rows = (
            await session.execute(
                text(REPROCESS_SQL),
                {"u": principal.user_id},
            )
        ).all()
    finally:
        await session.close()
    for (job_id,) in rows:
        enqueue(principal.tenant_id, UUID(str(job_id)))
    print(f"requeued {len(rows)} jobs", flush=True)


async def main(args: argparse.Namespace) -> None:
    engine = make_engine()
    try:
        principal = await resolve(engine, args.subject)
        if args.reprocess:
            await reprocess(engine, principal)
        else:
            await import_dir(engine, principal, Path(args.dir))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--dir", default="/import")
    parser.add_argument("--reprocess", action="store_true")
    asyncio.run(main(parser.parse_args()))
