"""Erase one user's account: rows, derived data, embeddings, and objects (ADR 0018).

Steps run in dependency order and are each idempotent, so a crashed or retried
job resumes by simply running again:

1. ``study_rows``  - the user's own study, tutor, assessment, weight, and push
   rows, children before parents (registry.DIRECT_DELETE_ORDER);
2. ``sources``     - every uploaded source not under legal hold: its object
   prefix first, then the shared per-source purge (pages, blocks, figures,
   chunks and embeddings, claims, mappings, jobs, orphaned concepts);
3. ``exports``     - export ZIPs and their rows;
4. ``identity``    - ``app.erase_user_identity``: users, memberships, and the
   user's audit trail, leaving one content-free audit record.

Sources under legal hold are skipped and reported by count and id; the user
row then survives only as an anonymous stub (no email, name, or login).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.library.service import purge_source_rows
from apps.worker.app.datarights import jobs, registry
from apps.worker.app.ingest.db import tenant_tx
from packages.library import storage
from sqlalchemy import text


async def run_delete(deps: jobs.DataDeps, tenant_id: UUID, job_id: UUID) -> str:
    async with tenant_tx(deps.engine, tenant_id) as session:
        job = await jobs.load(session, job_id, "delete")
        if job is None:
            return "missing"
        if job["status"] == "succeeded":
            return "done"
        await jobs.start(session, job_id)
    user_id = UUID(str(job["user_id"]))
    rows = await _delete_study_rows(deps, tenant_id, job_id, user_id)
    held = await _delete_sources(deps, tenant_id, job_id, user_id)
    exports = await _delete_exports(deps, tenant_id, job_id, user_id)
    async with tenant_tx(deps.engine, tenant_id) as session:
        await jobs.set_step(session, job_id, "identity")
        identity = (
            await session.execute(text("SELECT app.erase_user_identity(:u)"), {"u": user_id})
        ).scalar_one()
        await jobs.finish(session, job_id, {
            "study_rows": rows, "held_sources": len(held), "exports_removed": exports,
            "identity": str(identity),
        })
    return "succeeded"


async def _delete_study_rows(
    deps: jobs.DataDeps, tenant_id: UUID, job_id: UUID, user_id: UUID
) -> int:
    total = 0
    async with tenant_tx(deps.engine, tenant_id) as session:
        await jobs.set_step(session, job_id, "study_rows")
        for table in registry.DIRECT_DELETE_ORDER:
            result: Any = await session.execute(text(registry.delete_sql(table)), {"u": user_id})
            total += int(result.rowcount or 0)
    return total


async def _delete_sources(
    deps: jobs.DataDeps, tenant_id: UUID, job_id: UUID, user_id: UUID
) -> list[str]:
    async with tenant_tx(deps.engine, tenant_id) as session:
        await jobs.set_step(session, job_id, "sources")
        rows = (
            await session.execute(
                text("SELECT id, legal_hold FROM sources WHERE uploaded_by = :u"),
                {"u": user_id},
            )
        ).all()
    held = [str(source_id) for source_id, on_hold in rows if on_hold]
    for source_id, on_hold in rows:
        if on_hold:
            continue
        deps.store.delete_prefix(storage.source_prefix(tenant_id, source_id) + "/")
        async with tenant_tx(deps.engine, tenant_id) as session:
            await purge_source_rows(session, source_id)
    if held:
        async with tenant_tx(deps.engine, tenant_id) as session:
            await jobs.set_step(session, job_id, "sources", {"held_source_ids": held})
    return held


async def _delete_exports(
    deps: jobs.DataDeps, tenant_id: UUID, job_id: UUID, user_id: UUID
) -> int:
    async with tenant_tx(deps.engine, tenant_id) as session:
        await jobs.set_step(session, job_id, "exports")
        rows = (
            await session.execute(
                text("SELECT id FROM data_jobs WHERE user_id = :u AND kind = 'export'"),
                {"u": user_id},
            )
        ).scalars().all()
    for export_id in rows:
        deps.store.delete_prefix(storage.export_key(tenant_id, export_id))
    async with tenant_tx(deps.engine, tenant_id) as session:
        await session.execute(
            text("DELETE FROM data_jobs WHERE user_id = :u AND kind = 'export' "
                 "AND id = ANY(:ids)"),
            {"u": user_id, "ids": list(rows)},
        )
    return len(rows)
