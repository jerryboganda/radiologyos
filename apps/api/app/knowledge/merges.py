"""Reversible concept merges (Resolver agent and owner review; ADR 0030).

``apply_merge`` moves the merged concept's claims, movable edges, and
conflicts to the survivor, adds its names and keys to the survivor, points it
at the survivor (``merged_into``), and records exactly what moved in the
``concept_merges.snapshot``. ``undo_merge`` moves those rows back and removes
only what the merge added. Both run in the caller's tenant transaction (RLS)
and are shared by the worker and the API; neither commits.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from packages.knowledge.adjudication import merge_additions, without
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MergeConflict(ValueError):
    """The concepts changed since the decision; the merge cannot be applied/undone."""


async def _concepts(session: AsyncSession, ids: Sequence[UUID]) -> dict[str, dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT id, name, normalized_name, aliases, alias_keys, curriculum_code, "
            "curriculum_confidence, merged_into FROM concepts WHERE id = ANY(:ids) "
            "ORDER BY id FOR UPDATE"
        ),
        {"ids": list(ids)},
    )
    return {str(r["id"]): dict(r) for r in rows.mappings()}


async def _ids(session: AsyncSession, sql: str, params: dict[str, Any]) -> list[str]:
    values: list[Any] = list((await session.execute(text(sql), params)).scalars())
    return [str(v) for v in values]


async def _move(session: AsyncSession, survivor: UUID, merged: UUID) -> dict[str, list[str]]:
    params = {"s": survivor, "m": merged}
    return {
        "claims": await _ids(session, "UPDATE claims SET concept_id = :s WHERE concept_id = :m "
                             "RETURNING id", params),
        "edges_out": await _ids(session, """
            UPDATE concept_edges e SET from_concept = :s
            WHERE e.from_concept = :m AND e.to_concept <> :s AND NOT EXISTS (
                SELECT 1 FROM concept_edges x WHERE x.from_concept = :s
                  AND x.to_concept = e.to_concept AND x.relation = e.relation)
            RETURNING e.id""", params),
        "edges_in": await _ids(session, """
            UPDATE concept_edges e SET to_concept = :s
            WHERE e.to_concept = :m AND e.from_concept <> :s AND NOT EXISTS (
                SELECT 1 FROM concept_edges x WHERE x.to_concept = :s
                  AND x.from_concept = e.from_concept AND x.relation = e.relation)
            RETURNING e.id""", params),
        "conflicts": await _ids(session, "UPDATE knowledge_conflicts SET concept_id = :s "
                                "WHERE concept_id = :m RETURNING id", params),
    }


async def apply_merge(
    session: AsyncSession, merge_id: UUID, survivor_id: UUID, merged_id: UUID
) -> dict[str, Any]:
    """Merge ``merged_id`` into ``survivor_id``; returns the stored snapshot."""
    rows = await _concepts(session, [survivor_id, merged_id])
    survivor, merged = rows.get(str(survivor_id)), rows.get(str(merged_id))
    if survivor is None or merged is None or survivor["merged_into"] or merged["merged_into"]:
        raise MergeConflict("a concept is missing or already merged")
    aliases, keys = merge_additions(survivor, merged)
    moved = await _move(session, survivor_id, merged_id)
    set_code = survivor["curriculum_code"] is None and merged["curriculum_code"] is not None
    await session.execute(
        text(
            "UPDATE concepts SET aliases = aliases || CAST(:a AS text[]), "
            "alias_keys = alias_keys || CAST(:k AS text[]), "
            "curriculum_code = CASE WHEN CAST(:set AS boolean) THEN CAST(:code AS text) "
            "ELSE curriculum_code END, curriculum_confidence = CASE WHEN CAST(:set AS boolean) "
            "THEN CAST(:conf AS real) ELSE curriculum_confidence END "
            "WHERE id = :s"
        ),
        {"a": aliases, "k": keys, "set": set_code, "code": merged["curriculum_code"],
         "conf": merged["curriculum_confidence"], "s": survivor_id},
    )
    await session.execute(text("UPDATE concepts SET merged_into = :s WHERE id = :m"),
                          {"s": survivor_id, "m": merged_id})
    snapshot = {**moved, "aliases_added": aliases, "keys_added": keys,
                "curriculum_set": merged["curriculum_code"] if set_code else None}
    await session.execute(
        text(
            "UPDATE concept_merges SET status = 'applied', survivor = :s, merged = :m, "
            "snapshot = CAST(:snap AS jsonb), applied_at = now(), undone_at = NULL "
            "WHERE id = :id"
        ),
        {"s": survivor_id, "m": merged_id, "snap": json.dumps(snapshot), "id": merge_id},
    )
    return snapshot


async def _move_back(
    session: AsyncSession, snap: dict[str, Any], survivor: UUID, merged: UUID
) -> None:
    params = {"s": survivor, "m": merged}
    moves = (
        ("claims", "UPDATE claims SET concept_id = :m WHERE id = ANY(:ids) AND concept_id = :s"),
        ("edges_out", "UPDATE concept_edges SET from_concept = :m "
                      "WHERE id = ANY(:ids) AND from_concept = :s"),
        ("edges_in", "UPDATE concept_edges SET to_concept = :m "
                     "WHERE id = ANY(:ids) AND to_concept = :s"),
        ("conflicts", "UPDATE knowledge_conflicts SET concept_id = :m "
                      "WHERE id = ANY(:ids) AND concept_id = :s"),
    )
    for key, sql in moves:
        ids = [UUID(i) for i in snap.get(key) or []]
        if ids:
            await session.execute(text(sql), {**params, "ids": ids})


async def undo_merge(session: AsyncSession, merge: dict[str, Any], user_id: UUID) -> None:
    """Reverse an applied merge exactly (claims, edges, conflicts, aliases, code)."""
    survivor_id, merged_id = merge["survivor"], merge["merged"]
    rows = await _concepts(session, [survivor_id, merged_id])
    survivor, merged = rows.get(str(survivor_id)), rows.get(str(merged_id))
    if survivor is None or merged is None or survivor["merged_into"] is not None:
        raise MergeConflict("undo the later merge of the surviving concept first")
    if str(merged["merged_into"]) != str(survivor_id):
        raise MergeConflict("the merge is no longer in place")
    snap: dict[str, Any] = merge["snapshot"] or {}
    await _move_back(session, snap, survivor_id, merged_id)
    code = snap.get("curriculum_set")
    await session.execute(
        text(
            "UPDATE concepts SET aliases = :a, alias_keys = :k, "
            "curriculum_confidence = CASE WHEN curriculum_code = CAST(:code AS text) "
            "THEN NULL ELSE curriculum_confidence END, "
            "curriculum_code = CASE WHEN curriculum_code = CAST(:code AS text) "
            "THEN NULL ELSE curriculum_code END WHERE id = :s"
        ),
        {"a": without(survivor["aliases"] or [], snap.get("aliases_added") or []),
         "k": without(survivor["alias_keys"] or [], snap.get("keys_added") or []),
         "code": code, "s": survivor_id},
    )
    await session.execute(text("UPDATE concepts SET merged_into = NULL WHERE id = :m"),
                          {"m": merged_id})
    await session.execute(
        text("UPDATE concept_merges SET status = 'undone', undone_at = now(), "
             "decided_by = :u WHERE id = :id"),
        {"u": user_id, "id": merge["id"]},
    )


async def record_decision(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, pair: tuple[UUID, UUID],
    similarity: float, decision: dict[str, Any], status: str, agent: str,
) -> UUID | None:
    """Insert one decision per unordered pair; None when the pair was decided already."""
    created = await session.execute(
        text(
            """
            INSERT INTO concept_merges (tenant_id, user_id, concept_a, concept_b, similarity,
                decision, confidence, rationale, status, agent_version)
            VALUES (:t, :u, :a, :b, :sim, :d, :c, :r, :status, :agent)
            ON CONFLICT (tenant_id, concept_a, concept_b) DO NOTHING
            RETURNING id
            """
        ),
        {"t": tenant_id, "u": user_id, "a": pair[0], "b": pair[1],
         "sim": round(similarity, 4), "d": decision["decision"],
         "c": decision["confidence"], "r": decision["rationale"][:1000],
         "status": status, "agent": agent},
    )
    value = created.scalar_one_or_none()
    return UUID(str(value)) if value is not None else None
