"""Run (or resume) knowledge extraction for one source.

Status lives in the ingest job's ``knowledge_extraction`` step (``job_steps``),
so it is visible beside the other pipeline steps and keyed on the pipeline
version. Per-unit progress lives in ``knowledge_runs``. A usage-limit pause
returns the step to ``pending`` and the task reschedules itself.
"""

from __future__ import annotations

from uuid import UUID

from apps.worker.app.ingest import db as ingest_db
from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge import db
from apps.worker.app.knowledge.notes import Continue as NotesContinue
from apps.worker.app.knowledge.notes import run_notes
from apps.worker.app.knowledge.papers import run_papers
from apps.worker.app.knowledge.runtime import Deferred, KnowledgeDeps

STEP = "knowledge_extraction"
MODES = ("notes", "past_paper")


async def run_knowledge(
    deps: KnowledgeDeps, tenant_id: UUID, source_id: UUID, mode: str = "notes",
    exam_target: str | None = None, year: int | None = None,
) -> str:
    if mode not in MODES:
        raise ValueError("unknown knowledge mode")
    async with tenant_tx(deps.engine, tenant_id) as session:
        source = await db.load_source(session, source_id)
        job = await db.ingest_job(session, source_id)
        if source is None or job is None:
            return "missing"
        if await ingest_db.step_status(session, job["id"], STEP) == "succeeded":
            return "skipped"
        if deps.transport is None:
            await ingest_db.mark_step(session, job, STEP, "skipped", "no_model_transport")
            return "skipped"
        await ingest_db.mark_step(session, job, STEP, "running")
    version = int(job["pipeline_version"])
    try:
        if mode == "past_paper":
            summary = await run_papers(deps, tenant_id, source, version, exam_target, year)
        else:
            summary = await run_notes(deps, tenant_id, source, version)
    except Deferred:
        async with tenant_tx(deps.engine, tenant_id) as session:
            await ingest_db.mark_step(session, job, STEP, "pending", "usage_limit")
        return "deferred"
    except NotesContinue:
        async with tenant_tx(deps.engine, tenant_id) as session:
            await ingest_db.mark_step(session, job, STEP, "pending", "continuing")
        return "continue"
    except Exception:
        async with tenant_tx(deps.engine, tenant_id) as session:
            await ingest_db.mark_step(session, job, STEP, "failed", "knowledge_error")
        raise
    async with tenant_tx(deps.engine, tenant_id) as session:
        await ingest_db.mark_step(session, job, STEP, "succeeded",
                                  output_ref=f"{mode}:{summary}"[:200])
    return "succeeded"
