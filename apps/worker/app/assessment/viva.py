"""Run one unit of examiner work (idempotent per session, turn, ``PIPELINE_VERSION``).

1. In a tenant transaction: lock the session; stop unless its pending work is
   for this turn and claimable; read the turns; re-read the evidence text from
   the owner's live sources; mark the work running.
2. Outside any transaction: ``run_step`` calls the examiner (may take minutes).
3. In a tenant transaction: re-lock; apply the outcome only if the same work
   is still running (an early end or a newer step wins), then finish or wait
   for the candidate's next answer.

Only ids, turn numbers, outcome kinds, and error codes are logged, never
answers, transcripts, excerpts, or prompts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from apps.api.app.assessment import viva_evidence, viva_flow, viva_store
from apps.api.app.core.time import now_utc
from apps.worker.app.ingest.db import tenant_tx
from packages.assessment.grading_jobs import claimable
from packages.assessment.validation import Excerpt
from packages.assessment.viva import PIPELINE_VERSION
from packages.assessment.viva_steps import Snapshot, StepOutcome, run_step
from packages.models.gateway import Transport
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.assessment")


def snapshot(row: Mapping[str, Any], turns: Sequence[Mapping[str, Any]],
             evidence: Sequence[Excerpt]) -> Snapshot:
    return Snapshot(
        kind=row["kind"], style=row["style"], topic=row["topic"], scenario=row["scenario"],
        level=int(row["level"]), miss_streak=int(row["miss_streak"]),
        max_turns=int(row["max_turns"]), deadline_at=row["deadline_at"],
        case_data=row["case_data"] or {}, evidence=list(evidence), turns=list(turns),
        work_turn=int(row["work_turn"]), errors=int(row["errors"]), runs=int(row["runs"]),
    )


def needs_evidence(row: Mapping[str, Any]) -> bool:
    """A staged case needs source text only to write its rubric (turn 0)."""
    return row["kind"] == "viva" or int(row["work_turn"]) == 0


async def _claim(
    engine: AsyncEngine, tenant_id: UUID, session_id: UUID, turn_no: int
) -> tuple[str, Snapshot | None, bool]:
    async with tenant_tx(engine, tenant_id) as db:
        row = await viva_store.load_session(db, None, session_id, lock=True)
        if row is None:
            return "missing", None, False
        if int(row["work_turn"]) != turn_no or row["work"] == "none":
            return "done", None, False
        if not claimable(row["work"], row["updated_at"], now_utc()):
            return "busy", None, False
        turns = await viva_store.load_turns(db, session_id)
        evidence: list[Excerpt] = []
        if needs_evidence(row):
            evidence = await viva_evidence.hydrate(db, row["user_id"], row["evidence"])
        await viva_store.update_session(db, session_id,
                                        {"work": "running", "runs": int(row["runs"]) + 1})
    ok = not needs_evidence(row) or viva_evidence.has_text(evidence)
    return "claimed", snapshot(row, turns, evidence), ok


async def run_viva_step(
    engine: AsyncEngine, transport: Transport | None, tenant_id: UUID, session_id: UUID,
    turn_no: int, version: int = PIPELINE_VERSION,
) -> str:
    """Return applied, deferred, retry, failed, done, busy, missing, superseded, or stale."""
    if version != PIPELINE_VERSION:
        return "stale"
    state, snap, has_evidence = await _claim(engine, tenant_id, session_id, turn_no)
    if snap is None:
        return state
    if not has_evidence:
        outcome = StepOutcome("failed", error="evidence_gone")
    else:
        outcome = await asyncio.to_thread(run_step, transport, snap, now_utc())
    async with tenant_tx(engine, tenant_id) as db:
        row = await viva_store.load_session(db, None, session_id, lock=True)
        if row is None or row["work"] != "running" or int(row["work_turn"]) != turn_no:
            return "superseded"
        await viva_flow.apply_outcome(db, row, outcome, now_utc())
    log.info("viva step session=%s turn=%s outcome=%s code=%s", session_id, turn_no,
             outcome.kind, outcome.error)
    return outcome.kind
