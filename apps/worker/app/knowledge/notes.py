"""Notes mode: per chunk, extract cited knowledge and map it to the curriculum.

Each chunk is one resumable unit keyed by a hash of its text, the agent version,
and the pipeline version (``knowledge_runs``): a re-run or a resumed deferral
skips chunks already done, and re-chunking identical text does not re-extract.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from apps.worker.app.ingest.db import tenant_tx
from apps.worker.app.knowledge import db, graph
from apps.worker.app.knowledge.runtime import KnowledgeDeps, call_agent
from packages.knowledge.curriculum import mapping_status, prompt_listing
from packages.knowledge.evidence import FilteredExtraction, filter_extraction, locate_blocks
from packages.knowledge.models import KnowledgeExtraction, TopicClassification
from packages.knowledge.text import normalize_name, word_count
from packages.library.quality import extraction_problem
from packages.models.gateway import load_agent, user_prompt

log = logging.getLogger("radbrain.knowledge")
# The run labels are the versions ``call_agent`` actually loads, so a prompt bump
# makes every chunk a new unit and re-extracts it (knowledge_runs is keyed on it).
EXTRACT = load_agent("knowledge_extract").key
CLASSIFY = load_agent("topic_classify").key
MIN_WORDS = 30  # spec: chunks under ~40 tokens are skipped


def _extract_prompt(source: dict[str, Any], chunk: dict[str, Any]) -> str:
    return user_prompt("knowledge_extract", source_title=str(source["title"]),
                       heading_path=str(chunk["heading"] or "(none)"),
                       page_from=str(chunk["page_from"]), page_to=str(chunk["page_to"]),
                       chunk_text=str(chunk["text"]))


def _classify_prompt(chunk: dict[str, Any], concepts: list[str]) -> str:
    return user_prompt("topic_classify", curriculum_codes=prompt_listing(),
                       heading_path=str(chunk["heading"] or "(none)"),
                       concepts=", ".join(concepts) or "(none)", chunk_text=str(chunk["text"]))


def _evidence_problem(extraction: Any, chunk_text: str) -> str | None:
    kept = filter_extraction(extraction, chunk_text)
    return extraction_problem(kept.rejected_claims, len(kept.claims))


UNITS_PER_RUN = 20


class Continue(Exception):
    """Run budget reached; the task re-queues itself (keeps runs under the
    broker's visibility timeout so a job is never delivered twice)."""


async def run_notes(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], version: int
) -> str:
    """Process every eligible chunk; returns a stable summary for job_steps."""
    async with tenant_tx(deps.engine, tenant_id) as session:
        chunks = await db.chunks(session, source["id"])
    totals = {"chunks": 0, "claims": 0, "rejected": 0, "failed": 0}
    worked = 0
    for chunk in chunks:
        if word_count(chunk["text"]) < MIN_WORDS:
            continue
        if worked >= UNITS_PER_RUN:
            raise Continue
        outcome = await _chunk(deps, tenant_id, source, chunk, version)
        if outcome:
            worked += 1
        totals["chunks"] += 1
        for key, value in outcome.items():
            totals[key] = totals.get(key, 0) + value
    return ",".join(f"{k}:{v}" for k, v in totals.items())


async def _chunk(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], chunk: dict[str, Any],
    version: int,
) -> dict[str, int]:
    unit = f"chunk:{db.unit_hash(chunk['text'])}"
    async with tenant_tx(deps.engine, tenant_id) as session:
        if await db.run_done(session, source["id"], unit, EXTRACT, version):
            return {}
    extraction = call_agent(deps, "knowledge_extract", _extract_prompt(source, chunk),
                            accept=lambda e: _evidence_problem(e, chunk["text"]))
    if extraction is None:
        async with tenant_tx(deps.engine, tenant_id) as session:
            await db.record_run(session, tenant_id, source["id"], unit, EXTRACT, version,
                                "failed", "model_error")
        return {"failed": 1}
    assert isinstance(extraction, KnowledgeExtraction)
    kept = filter_extraction(extraction, chunk["text"])
    names = [c.name for c in kept.concepts]
    classified = call_agent(deps, "topic_classify", _classify_prompt(chunk, names))
    async with tenant_tx(deps.engine, tenant_id) as session:
        stored = await _persist(session, tenant_id, source, chunk, unit, kept)
        if isinstance(classified, TopicClassification):
            await _map(session, tenant_id, source, chunk, unit, classified, stored)
        await db.record_run(session, tenant_id, source["id"], unit, EXTRACT, version,
                            "succeeded", f"claims:{len(kept.claims)},rej:{kept.rejected_claims}")
    if kept.rejected_claims:
        log.info("knowledge rejected_claims=%s source=%s unit=%s",
                 kept.rejected_claims, source["id"], unit)
    return {"claims": len(kept.claims), "rejected": kept.rejected_claims}


def _citation(source: dict[str, Any], chunk: dict[str, Any], blocks: list[dict[str, Any]],
              span: str) -> dict[str, Any]:
    return {
        "source_id": str(source["id"]), "source_title": source["title"],
        "chunk_id": str(chunk["id"]), "page_from": chunk["page_from"],
        "page_to": chunk["page_to"], "blocks": locate_blocks(span, blocks) if span else [],
    }


async def _persist(
    session: Any, tenant_id: UUID, source: dict[str, Any], chunk: dict[str, Any], unit: str,
    kept: FilteredExtraction,
) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for concept in kept.concepts:
        ids[normalize_name(concept.name)] = await graph.resolve_concept(session, tenant_id, concept)
    blocks = await db.blocks_for_pages(session, source["id"], chunk["page_from"], chunk["page_to"])
    meta = {"source_id": source["id"], "chunk_id": chunk["id"], "page_from": chunk["page_from"],
            "page_to": chunk["page_to"], "agent": EXTRACT, "unit": unit}
    for claim in kept.claims:
        concept_id = ids[normalize_name(claim.concept)]
        citation = _citation(source, chunk, blocks, claim.evidence_span)
        await graph.store_claim(session, tenant_id, concept_id, claim, citation, meta)
    for relation in kept.relations:
        citation = _citation(source, chunk, [], "")
        await graph.store_edge(session, tenant_id, ids[normalize_name(relation.src)],
                               ids[normalize_name(relation.dst)], relation.relation,
                               citation, meta)
    return ids


async def _map(
    session: Any, tenant_id: UUID, source: dict[str, Any], chunk: dict[str, Any], unit: str,
    result: TopicClassification, concept_ids: dict[str, UUID],
) -> None:
    meta = {"source_id": source["id"], "chunk_id": chunk["id"], "page_from": chunk["page_from"],
            "page_to": chunk["page_to"], "agent": CLASSIFY, "unit": unit}
    first = True
    for mapping in result.topics:
        status = mapping_status(mapping.curriculum_code, mapping.confidence)
        if status is None:
            continue
        targets = list(concept_ids.values()) if first else []
        await graph.store_mapping(session, tenant_id, mapping, status, targets, meta)
        first = False
