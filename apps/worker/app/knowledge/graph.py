"""Persist resolved concepts, cited claims, edges, conflicts, and mappings.

All writes run in the caller's tenant transaction (RLS). A contradiction never
overwrites an existing claim: it creates an explicit ``knowledge_conflicts`` row
and marks both claims ``disputed`` (spec section 5, CLAUDE.md non-negotiables).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.worker.app.ingest.db import as_json
from packages.knowledge.conflicts import compare_claims
from packages.knowledge.curriculum import NodeMapping
from packages.knowledge.models import ExtractedClaim, ExtractedConcept, TopicMapping
from packages.knowledge.resolution import Candidate, decide, merged_aliases
from packages.knowledge.text import CANDIDATE, alias_keys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _candidates(session: AsyncSession, keys: list[str]) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT id, name, normalized_name, aliases, alias_keys FROM concepts
            WHERE merged_into IS NULL AND (normalized_name = ANY(CAST(:keys AS text[]))
               OR alias_keys && CAST(:keys AS text[])
               OR similarity(normalized_name, :key) >= :floor)
            ORDER BY similarity(normalized_name, :key) DESC
            LIMIT 8
            """
        ),
        {"keys": keys, "key": keys[0], "floor": CANDIDATE},
    )
    return [dict(row) for row in rows.mappings()]


async def resolve_concept(
    session: AsyncSession, tenant_id: UUID, concept: ExtractedConcept
) -> UUID:
    """Merge into an existing concept (alias/near-exact) or create a new one.

    Concepts merged away by the Resolver (ADR 0030) are never candidates; their
    names and keys live on the survivor, so new mentions resolve there.
    """
    keys = alias_keys(concept.name, concept.aliases)
    rows = await _candidates(session, keys)
    decision = decide(keys, [
        Candidate(r["id"], r["normalized_name"], tuple(r["alias_keys"] or ())) for r in rows
    ])
    if decision.action == "merge" and decision.concept_id is not None:
        row = next(r for r in rows if r["id"] == decision.concept_id)
        extra = [a.strip() for a in (concept.name, *concept.aliases) if a.strip() != row["name"]]
        aliases, merged_keys = merged_aliases(
            row["aliases"] or [], row["alias_keys"] or [], extra, keys
        )
        await session.execute(
            text("UPDATE concepts SET aliases = :a, alias_keys = :k WHERE id = :id"),
            {"a": aliases, "k": merged_keys, "id": row["id"]},
        )
        return UUID(str(row["id"]))
    created = await session.execute(
        text(
            """
            INSERT INTO concepts (tenant_id, name, normalized_name, concept_type, aliases,
                                  alias_keys)
            VALUES (:t, :name, :key, :type, :aliases, :keys)
            ON CONFLICT (tenant_id, normalized_name) DO UPDATE SET name = concepts.name
            RETURNING coalesce(merged_into, id)
            """
        ),
        {"t": tenant_id, "name": concept.name.strip()[:300], "key": keys[0][:300],
         "type": concept.type, "aliases": [a.strip() for a in concept.aliases if a.strip()],
         "keys": keys},
    )
    return UUID(str(created.scalar_one()))


async def store_claim(
    session: AsyncSession, tenant_id: UUID, concept_id: UUID, claim: ExtractedClaim,
    citation: dict[str, Any], meta: dict[str, Any],
) -> str:
    """Insert a claim, merge a duplicate, or record conflicts. Returns the outcome.

    A claim the extractor doubts (its source contradicts standard teaching) is
    stored as ``flagged`` for the owner's review, outside conflict detection.
    """
    if (getattr(claim, "source_doubt", "") or "").strip():
        await _insert_claim(session, tenant_id, concept_id, claim, citation, meta)
        return "flagged"
    rows = (await session.execute(
        text("SELECT id, statement, source_id FROM claims WHERE concept_id = :c "
             "AND status IN ('active', 'disputed')"),
        {"c": concept_id},
    )).mappings().all()
    conflicts = []
    for row in rows:
        verdict = compare_claims(row["statement"], claim.text)
        if verdict is None:
            continue
        if verdict.kind == "duplicate":
            if str(row["source_id"]) != str(meta["source_id"]):
                await session.execute(
                    text("UPDATE claims SET supporting = supporting || CAST(:c AS jsonb), "
                         "verification = 'verified' WHERE id = :id"),
                    {"c": as_json([citation]), "id": row["id"]},
                )
            return "merged"
        conflicts.append((row["id"], verdict))
    new_id = await _insert_claim(session, tenant_id, concept_id, claim, citation, meta)
    for other_id, verdict in conflicts:
        await session.execute(
            text(
                "INSERT INTO knowledge_conflicts (tenant_id, concept_id, claim_a, claim_b, kind, "
                "description) VALUES (:t, :c, :a, :b, :k, :d) ON CONFLICT DO NOTHING"
            ),
            {"t": tenant_id, "c": concept_id, "a": other_id, "b": new_id, "k": verdict.kind,
             "d": verdict.description[:1000]},
        )
        await session.execute(
            text("UPDATE claims SET status = 'disputed' WHERE id IN (:a, :b)"),
            {"a": other_id, "b": new_id},
        )
    return "conflict" if conflicts else "inserted"


async def _insert_claim(
    session: AsyncSession, tenant_id: UUID, concept_id: UUID, claim: ExtractedClaim,
    citation: dict[str, Any], meta: dict[str, Any],
) -> UUID:
    doubt = (getattr(claim, "source_doubt", "") or "").strip()
    created = await session.execute(
        text(
            """
            INSERT INTO claims (tenant_id, concept_id, claim_type, statement, evidence_span,
                source_id, chunk_id, page_from, page_to, citation, importance, modality,
                agent_version, status, doubt)
            VALUES (:t, :c, :type, :statement, :span, :s, :chunk, :pf, :pt,
                    CAST(:citation AS jsonb), :importance, :modality, :agent, :status, :doubt)
            RETURNING id
            """
        ),
        {"t": tenant_id, "c": concept_id, "type": claim.type, "statement": claim.text.strip(),
         "span": claim.evidence_span, "s": meta["source_id"], "chunk": meta["chunk_id"],
         "pf": meta["page_from"], "pt": meta["page_to"], "citation": as_json(citation),
         "importance": claim.importance, "modality": claim.modality[:40],
         "agent": meta["agent"], "status": "flagged" if doubt else "active",
         "doubt": doubt[:500] or None},
    )
    return UUID(str(created.scalar_one()))


async def store_edge(
    session: AsyncSession, tenant_id: UUID, src: UUID, dst: UUID, relation: str,
    citation: dict[str, Any], meta: dict[str, Any],
) -> None:
    if src == dst:
        return
    await session.execute(
        text(
            "INSERT INTO concept_edges (tenant_id, from_concept, to_concept, relation, "
            "source_id, citation, agent_version) VALUES (:t, :a, :b, :r, :s, "
            "CAST(:c AS jsonb), :agent) ON CONFLICT DO NOTHING"
        ),
        {"t": tenant_id, "a": src, "b": dst, "r": relation, "s": meta["source_id"],
         "c": as_json(citation), "agent": meta["agent"]},
    )


async def store_mapping(
    session: AsyncSession, tenant_id: UUID, mapping: TopicMapping, status: str,
    concept_ids: list[UUID], meta: dict[str, Any],
) -> None:
    """System-level classifier output (topic_classify v1/v2)."""
    node = NodeMapping(mapping.curriculum_code, mapping.curriculum_code, status)
    await store_node_mapping(session, tenant_id, node, mapping.topic, mapping.confidence,
                             concept_ids, meta)


async def store_node_mapping(
    session: AsyncSession, tenant_id: UUID, node: NodeMapping, topic: str, confidence: float,
    concept_ids: list[UUID], meta: dict[str, Any],
) -> None:
    """Store a mapping to a curriculum node at any depth (ADR 0023).

    ``node`` comes from ``packages.knowledge.curriculum.node_mapping``: its
    system goes to ``curriculum_code`` (what system-level readers use) and the
    node itself to ``curriculum_node_id``; status follows the < 0.7 review rule.
    """
    await session.execute(
        text(
            """
            INSERT INTO curriculum_mappings (tenant_id, source_id, unit_hash, chunk_id,
                page_from, page_to, curriculum_code, curriculum_node_id, topic, confidence,
                status, agent_version)
            VALUES (:t, :s, :u, :chunk, :pf, :pt, :code, :node, :topic, :conf, :status, :agent)
            ON CONFLICT (tenant_id, source_id, unit_hash, curriculum_code, topic)
            DO UPDATE SET confidence = EXCLUDED.confidence, status = EXCLUDED.status,
                chunk_id = EXCLUDED.chunk_id, curriculum_node_id = EXCLUDED.curriculum_node_id
            """
        ),
        {"t": tenant_id, "s": meta["source_id"], "u": meta["unit"], "chunk": meta["chunk_id"],
         "pf": meta["page_from"], "pt": meta["page_to"], "code": node.system,
         "node": node.node_id, "topic": topic.strip()[:200], "conf": confidence,
         "status": node.status, "agent": meta["agent"]},
    )
    if node.status == "accepted" and concept_ids:
        await session.execute(
            text(
                "UPDATE concepts SET curriculum_code = :code, curriculum_confidence = :conf "
                "WHERE id = ANY(CAST(:ids AS uuid[])) AND (curriculum_code IS NULL "
                "OR coalesce(curriculum_confidence, 0) < :conf)"
            ),
            {"code": node.system, "conf": confidence, "ids": list(concept_ids)},
        )
