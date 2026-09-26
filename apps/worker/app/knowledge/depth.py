"""Knowledge depth pass for one source: Conflict, Resolver, and Synthesis agents.

Runs after ``knowledge_extraction`` succeeds (ADR 0030). Status is the ingest
job's ``knowledge_depth`` step, keyed on the pipeline version and visible with
the other steps; per-unit progress is in ``knowledge_runs`` (one row per
conflict, concept pair, or concept+claims hash, agent version, and pipeline
version), so a re-run, a resumed usage-limit pause, or a budget continuation
repeats no model call. Order matters: conflicts first (so notes see settled
claim statuses), then merges (so notes are written for survivors), then notes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.worker.app.ingest import db as ingest_db
from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge import db
from apps.worker.app.knowledge.budget import Budget
from apps.worker.app.knowledge.concept_notes import synthesize_source
from apps.worker.app.knowledge.conflict_agent import classify_conflicts
from apps.worker.app.knowledge.notes import Continue
from apps.worker.app.knowledge.resolver import resolve_pairs
from apps.worker.app.knowledge.runtime import Deferred, KnowledgeDeps

STEP = "knowledge_depth"


async def run_depth(
    deps: KnowledgeDeps, tenant_id: UUID, source_id: UUID, fresh: bool = False
) -> str:
    """Run (or resume) the depth pass; ``fresh`` re-opens a finished step."""
    async with tenant_tx(deps.engine, tenant_id) as session:
        source = await db.load_source(session, source_id)
        job = await db.ingest_job(session, source_id)
        if source is None or job is None:
            return "missing"
        status = await ingest_db.step_status(session, job["id"], STEP)
        if status == "succeeded" and not fresh:
            return "skipped"
        if deps.transport is None:
            await ingest_db.mark_step(session, job, STEP, "skipped", "no_model_transport")
            return "skipped"
        await ingest_db.mark_step(session, job, STEP, "running")
    version = int(job["pipeline_version"])
    budget = Budget()
    try:
        conflicts = await classify_conflicts(deps, tenant_id, source, version, budget)
        pairs = await resolve_pairs(deps, tenant_id, source, version, budget)
        notes = await synthesize_source(deps, tenant_id, source, version, budget)
    except Deferred:
        return await _pause(deps, tenant_id, job, "usage_limit", "deferred")
    except Continue:
        return await _pause(deps, tenant_id, job, "continuing", "continue")
    except Exception:
        async with tenant_tx(deps.engine, tenant_id) as session:
            await ingest_db.mark_step(session, job, STEP, "failed", "knowledge_depth_error")
        raise
    async with tenant_tx(deps.engine, tenant_id) as session:
        await ingest_db.mark_step(session, job, STEP, "succeeded",
                                  output_ref=f"conflicts:{conflicts},pairs:{pairs},notes:{notes}")
    return "succeeded"


async def _pause(deps: KnowledgeDeps, tenant_id: UUID, job: dict[str, Any], code: str,
                 outcome: str) -> str:
    async with tenant_tx(deps.engine, tenant_id) as session:
        await ingest_db.mark_step(session, job, STEP, "pending", code)
    return outcome
