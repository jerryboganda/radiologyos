"""Synthesis agent: a cited canonical note per (owner, concept) (ADR 0030).

The note is built only from the owner's active/disputed claims on the concept
(``extract`` route, ``concept_synthesis``). Every sentence must cite supplied
claim labels and be lexically supported by them; the rest is dropped and a
note with no supported sentence is not stored (fail closed). Notes are
versioned and keyed by the hash of their claims, so a re-run with unchanged
claims makes no model call, and a changed claim set yields a new ``draft``
version that supersedes the old one. Only the owner can mark a note verified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.api.app.knowledge.service import live_concept_id
from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge import db, depth_db
from apps.worker.app.knowledge.budget import Budget
from apps.worker.app.knowledge.runtime import KnowledgeDeps, call_agent
from packages.knowledge.agents import ConceptNote
from packages.knowledge.synthesis import (
    build_prompt,
    check_note,
    claims_hash,
    label_claims,
    note_problem,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AGENT = "concept_synthesis/v1"
AUTO_MIN_CLAIMS = 3  # automatic notes only for concepts with some substance


@dataclass(slots=True)
class Prepared:
    concept: dict[str, Any]
    claims: list[dict[str, Any]]
    differentials: list[dict[str, Any]]
    digest: str


async def _make_current(session: AsyncSession, user_id: UUID, concept_id: UUID,
                        digest: str) -> bool:
    """Reinstate an existing note for these exact claims; False when none exists."""
    found = (await session.execute(
        text("SELECT id FROM concept_notes WHERE user_id = :u AND concept_id = :c "
             "AND claims_hash = :h AND agent_version = :a"),
        {"u": user_id, "c": concept_id, "h": digest, "a": AGENT},
    )).scalar_one_or_none()
    if found is None:
        return False
    await session.execute(
        text("UPDATE concept_notes SET status = CASE WHEN id = :id THEN CASE WHEN "
             "verified_at IS NULL THEN 'draft' ELSE 'verified' END ELSE 'superseded' END "
             "WHERE user_id = :u AND concept_id = :c"),
        {"id": found, "u": user_id, "c": concept_id},
    )
    return True


async def prepare(session: AsyncSession, user_id: UUID, concept_id: UUID,
                  min_claims: int) -> Prepared | str:
    """What a note would be built from, or why none is needed/possible."""
    concept_id = await live_concept_id(session, concept_id)
    concept = await depth_db.concept(session, concept_id)
    if concept is None:
        return "missing"
    claims = await depth_db.owner_claims(session, user_id, concept_id)
    if len(claims) < max(1, min_claims):
        return "too_few_claims"
    digest = claims_hash(claims)
    if await _make_current(session, user_id, concept_id, digest):
        return "unchanged"
    return Prepared(concept, claims, await depth_db.differentials(session, concept_id), digest)


async def write(deps: KnowledgeDeps, tenant_id: UUID, user_id: UUID, prepared: Prepared,
                version: int) -> str:
    """Call the Synthesis agent, check every sentence, store a new draft version."""
    labels = label_claims(prepared.claims)
    ddx = prepared.differentials
    prompt = build_prompt(prepared.concept, labels, [d["name"] for d in ddx])

    def gate(note: BaseModel) -> str | None:
        return note_problem(note, labels) if isinstance(note, ConceptNote) else "wrong_type"

    note = call_agent(deps, "concept_synthesis", prompt, accept=gate)
    if not isinstance(note, ConceptNote):
        return "failed"
    checked = check_note(note, labels, {d["normalized_name"]: str(d["id"]) for d in ddx})
    if checked.kept == 0:
        return "unsupported"
    async with tenant_tx(deps.engine, tenant_id) as session:
        await _store(session, tenant_id, user_id, prepared, checked, version)
    return "stored"


async def _store(session: AsyncSession, tenant_id: UUID, user_id: UUID, prepared: Prepared,
                 checked: Any, version: int) -> None:
    concept_id = prepared.concept["id"]
    await session.execute(
        text("UPDATE concept_notes SET status = 'superseded' WHERE user_id = :u "
             "AND concept_id = :c AND status <> 'superseded'"),
        {"u": user_id, "c": concept_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO concept_notes (tenant_id, user_id, concept_id, version, claims_hash,
                status, body, claim_ids, sentences, dropped, agent_version, pipeline_version)
            VALUES (:t, :u, :c, (SELECT coalesce(max(version), 0) + 1 FROM concept_notes
                                 WHERE user_id = :u AND concept_id = :c),
                    :h, 'draft', CAST(:body AS jsonb), CAST(:ids AS uuid[]), :n, :d, :a, :v)
            ON CONFLICT (tenant_id, user_id, concept_id, claims_hash, agent_version) DO NOTHING
            """
        ),
        {"t": tenant_id, "u": user_id, "c": concept_id, "h": prepared.digest,
         "body": json.dumps(checked.body, ensure_ascii=False),
         "ids": [UUID(i) for i in checked.claim_ids],
         "n": checked.kept, "d": checked.dropped, "a": AGENT, "v": version},
    )


async def synthesize_concept(deps: KnowledgeDeps, tenant_id: UUID, user_id: UUID,
                             concept_id: UUID, version: int = 1) -> str:
    """On-demand note for one concept (the concept page's "regenerate")."""
    async with tenant_tx(deps.engine, tenant_id) as session:
        prepared = await prepare(session, user_id, concept_id, 1)
    if isinstance(prepared, str):
        return prepared
    return await write(deps, tenant_id, user_id, prepared, version)


async def synthesize_source(deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any],
                            version: int, budget: Budget) -> int:
    """Notes for the concepts a source touches (owner = uploader); returns stored count."""
    user_id = source["uploaded_by"]
    async with tenant_tx(deps.engine, tenant_id) as session:
        concept_ids = await depth_db.touched_concepts(session, source["id"])
    stored = 0
    for concept_id in concept_ids:
        async with tenant_tx(deps.engine, tenant_id) as session:
            prepared = await prepare(session, user_id, concept_id, AUTO_MIN_CLAIMS)
            if isinstance(prepared, str):
                continue
            unit = f"note:{prepared.concept['id']}:{prepared.digest[:16]}"
            if await db.run_done(session, source["id"], unit, AGENT, version):
                continue
        budget.spend()
        outcome = await write(deps, tenant_id, user_id, prepared, version)
        async with tenant_tx(deps.engine, tenant_id) as session:
            status = "succeeded" if outcome == "stored" else "skipped"
            await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                                status, outcome)
        stored += outcome == "stored"
    return stored
