"""Conflict agent: adjudicate heuristic conflicts with the ``reason`` route.

For every open, unclassified conflict that involves a claim of this source,
``claim_conflict`` labels the pair ``conflict`` / ``context`` / ``same`` with a
rationale citing [A] and/or [B]. The verdict is stored on the conflict; a
confident ``context``/``same`` closes it with both claims kept, anything else
stays open for the owner (ADR 0030). Each conflict is one unit in
``knowledge_runs`` (entity + agent version + pipeline version), so a re-run or
a resumed deferral never asks twice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.knowledge import trust
from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge import db, depth_db
from apps.worker.app.knowledge.budget import Budget
from apps.worker.app.knowledge.runtime import KnowledgeDeps, call_agent
from packages.knowledge.adjudication import conflict_action, conflict_resolution_text
from packages.knowledge.agents import ConflictVerdict

AGENT = "claim_conflict/v1"


def _side(label: str, statement: str, span: str, citation: dict[str, Any]) -> str:
    title = citation.get("source_title") or "source"
    pages = f"pp. {citation.get('page_from')}-{citation.get('page_to')}"
    return f"[{label}] {statement}\n    Span: \"{span}\"\n    Source: {title}, {pages}"


def conflict_prompt(row: dict[str, Any]) -> str:
    return "\n".join([
        f"Concept: {row['concept_name']}",
        f"Heuristic flag: {row['kind']}: {row['description']}",
        "",
        _side("A", row["a_statement"], row["a_span"], row["a_citation"] or {}),
        _side("B", row["b_statement"], row["b_span"], row["b_citation"] or {}),
    ])


async def classify_conflicts(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], version: int, budget: Budget
) -> int:
    async with tenant_tx(deps.engine, tenant_id) as session:
        rows = await depth_db.unclassified_conflicts(session, source["id"])
    done = 0
    for row in rows:
        unit = f"conflict:{row['id']}"
        async with tenant_tx(deps.engine, tenant_id) as session:
            if await db.run_done(session, source["id"], unit, AGENT, version):
                continue
        budget.spend()
        verdict = call_agent(deps, "claim_conflict", conflict_prompt(row))
        async with tenant_tx(deps.engine, tenant_id) as session:
            if not isinstance(verdict, ConflictVerdict):
                await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                                    "skipped", "model_error")
                continue
            await apply_verdict(session, row, verdict)
            await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                                "succeeded", verdict.label)
        done += 1
    return done


async def apply_verdict(session: Any, row: dict[str, Any], verdict: ConflictVerdict) -> str:
    """Store the verdict; close the conflict when the policy says so."""
    await trust.store_verdict(session, row["id"], verdict.model_dump(), AGENT)
    action = conflict_action(verdict.label, verdict.confidence)
    if action == "auto_resolve":
        text = conflict_resolution_text(verdict.label, verdict.rationale, verdict.context)
        await trust.close_conflict(session, row, text, None, None, None)
    return action
