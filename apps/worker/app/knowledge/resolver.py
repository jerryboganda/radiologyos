"""Resolver agent: adjudicate near-duplicate concepts with the ``reason`` route.

For each live concept this source touches, unmerged concepts whose best
name/alias trigram similarity lies in the 0.80-0.92 band (below the automatic
merge threshold) are shown to ``concept_resolver`` with a few of the owner's
claims for each. One decision is stored per unordered pair
(``concept_merges``): a confident merge is applied reversibly, a confident
distinct/parent-child is recorded, and anything less confident waits in the
owner's review queue (ADR 0030).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.knowledge import merges
from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge import db, depth_db
from apps.worker.app.knowledge.budget import Budget
from apps.worker.app.knowledge.runtime import KnowledgeDeps, call_agent
from packages.knowledge.adjudication import choose_survivor, pair_key, resolver_action
from packages.knowledge.agents import ResolverDecision
from packages.knowledge.text import AUTO_MERGE, CANDIDATE, trigram_similarity

AGENT = "concept_resolver/v1"


def band_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    keys_a = [a["normalized_name"], *(a.get("alias_keys") or [])]
    keys_b = [b["normalized_name"], *(b.get("alias_keys") or [])]
    return max(trigram_similarity(x, y) for x in keys_a for y in keys_b)


def summary(label: str, row: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    lines = [f"[{label}] {row['name']} ({row['concept_type']})",
             f"    Aliases: {', '.join(row.get('aliases') or []) or '(none)'}"]
    lines.extend(f"    - {c['statement']}" for c in claims[:4])
    return "\n".join(lines)


async def resolve_pairs(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], version: int, budget: Budget
) -> int:
    async with tenant_tx(deps.engine, tenant_id) as session:
        concept_ids = await depth_db.touched_concepts(session, source["id"])
    done = 0
    for concept_id in concept_ids:
        async with tenant_tx(deps.engine, tenant_id) as session:
            row = await depth_db.concept(session, concept_id)
            near = [] if row is None or row["merged_into"] else (
                await depth_db.near_concepts(session, row))
        for other in near:
            assert row is not None
            score = band_similarity(row, other)
            if not CANDIDATE <= score < AUTO_MERGE:
                continue
            action = await _pair(deps, tenant_id, source, version, budget, (row, other, score))
            done += action is not None
            if action == "merge":
                break  # this concept changed; later runs see the merged state
    return done


async def _pair(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], version: int, budget: Budget,
    item: tuple[dict[str, Any], dict[str, Any], float],
) -> str | None:
    row, other, score = item
    pair = pair_key(str(row["id"]), str(other["id"]))
    unit = f"pair:{pair[0]}:{pair[1]}"
    user = source["uploaded_by"]
    async with tenant_tx(deps.engine, tenant_id) as session:
        if await db.run_done(session, source["id"], unit, AGENT, version) or (
            await depth_db.pair_decided(session, UUID(pair[0]), UUID(pair[1]))
        ):
            return None
        claims_a = await depth_db.owner_claims(session, user, row["id"], 4)
        claims_b = await depth_db.owner_claims(session, user, other["id"], 4)
    budget.spend()
    prompt = (f"Trigram similarity: {score:.2f}\n\n{summary('A', row, claims_a)}\n\n"
              f"{summary('B', other, claims_b)}")
    decision = call_agent(deps, "concept_resolver", prompt)
    async with tenant_tx(deps.engine, tenant_id) as session:
        if not isinstance(decision, ResolverDecision):
            await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                                "skipped", "model_error")
            return None
        action = await apply_decision(session, tenant_id, user, (row, other, score), decision)
        await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                            "succeeded", action)
    return action


async def apply_decision(
    session: Any, tenant_id: UUID, user_id: UUID,
    item: tuple[dict[str, Any], dict[str, Any], float], decision: ResolverDecision,
) -> str:
    """Record the decision; apply a confident merge. Returns merge|distinct|review."""
    row, other, score = item
    action = resolver_action(decision.decision, decision.confidence)
    status = "distinct" if action == "distinct" else "review"
    pair = pair_key(str(row["id"]), str(other["id"]))
    merge_id = await merges.record_decision(
        session, tenant_id, user_id, (UUID(pair[0]), UUID(pair[1])), score,
        decision.model_dump(), status, AGENT)
    if merge_id is None or action != "merge":
        return action if merge_id is not None else "already_decided"
    survivor, merged = choose_survivor(row, other)
    try:
        await merges.apply_merge(session, merge_id, survivor["id"], merged["id"])
    except merges.MergeConflict:
        return "review"
    return "merge"
