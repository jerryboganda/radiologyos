"""Opt-in live proof of the knowledge pipeline against PostgreSQL (ADR 0016).

Runs the real worker code as the RLS-bound runtime role with a scripted model
transport (no network): verbatim-span enforcement, alias merge, explicit
numeric conflict, curriculum review queue, resumable idempotent re-runs, and
past-paper topic weights that stay unapproved until approved, all invisible to
another tenant.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

from evals.checks._knowledge_support import (  # noqa: E402
    ScriptedTransport,
    add_job,
    as_tenant,
    cleanup,
    require_env,
    seed,
)

CHUNK_A = (
    "Synthetic chest notes. Usual interstitial pneumonia (UIP) shows basal subpleural "
    "reticulation with honeycombing and traction bronchiectasis on HRCT. In this synthetic "
    "teaching note the typical age at presentation is over 60 years and men are affected "
    "more often than women."
)
CHUNK_B = (
    "Second synthetic paragraph. For UIP the typical age at presentation is over 50 years "
    "according to this contradictory synthetic note, which exists only to exercise the "
    "conflict detector of the knowledge pipeline in automated tests."
)


def _claim(concept: str, text: str, span: str) -> dict[str, Any]:
    return {"concept": concept, "type": "epidemiology", "text": text, "evidence_span": span,
            "importance": 4, "modality": ""}


def _extract(prompt: str) -> dict[str, Any]:
    if "Second synthetic" in prompt:
        return {"concepts": [{"name": "UIP", "type": "disease", "aliases": []}],
                "claims": [_claim("UIP", "Typical age at presentation of UIP is over 50 years",
                                  "typical age at presentation is over 50 years")],
                "relations": []}
    return {
        "concepts": [{"name": "Usual interstitial pneumonia", "type": "disease",
                      "aliases": ["UIP"]},
                     {"name": "Honeycombing", "type": "sign", "aliases": []}],
        "claims": [
            _claim("Usual interstitial pneumonia",
                   "Typical age at presentation of UIP is over 60 years",
                   "typical age at presentation is over 60 years"),
            _claim("Usual interstitial pneumonia", "UIP is most common in children",
                   "an invented span that is not in the chunk"),
        ],
        "relations": [{"src": "Honeycombing", "dst": "Usual interstitial pneumonia",
                       "relation": "sign_of"}],
    }


def _classify(prompt: str) -> dict[str, Any]:
    return {"topics": [
        {"curriculum_code": "CHEST", "topic": "usual interstitial pneumonia", "confidence": 0.9},
        {"curriculum_code": "PHYSICS", "topic": "hrct technique", "confidence": 0.4},
        {"curriculum_code": "NOT_A_CODE", "topic": "x", "confidence": 0.99},
    ]}


def _paper(prompt: str) -> dict[str, Any]:
    if "Page: 2" in prompt:
        return {"is_exam_paper": False, "exam_target": "unknown", "year": None,
                "paper_label": "", "questions": []}
    question = {"question_no": "1", "curriculum_node_id": "CHEST.PULM_VASC.PE",
                "topic": "pulmonary embolism", "confidence": 0.9}
    return {"is_exam_paper": True, "exam_target": "imm", "year": 2019,
            "paper_label": "IMM 2019 Paper I",
            "questions": [question, {**question, "question_no": "2"},
                          {**question, "question_no": "3", "curriculum_node_id": "GI",
                           "topic": "intussusception"},
                          {**question, "question_no": "4", "curriculum_node_id": "CHEST.MADE_UP"}]}


async def _seed_content(runtime: Any, ids: dict[str, UUID]) -> None:
    ta = ids["ta"]
    for n, body in enumerate((CHUNK_A, CHUNK_B, "Too short to extract.")):
        await as_tenant(runtime, ta, "INSERT INTO chunks (tenant_id, source_id, chunk_no, "
                        "page_from, page_to, text) VALUES ($1,$2,$3,1,1,$4)",
                        ta, ids["sa"], n, body)
        await as_tenant(runtime, ta, "INSERT INTO source_blocks (tenant_id, source_id, page_no, "
                        "block_no, kind, text, bbox, origin) VALUES "
                        "($1,$2,1,$3,'paragraph',$4,'{0,0,1,1}','native')", ta, ids["sa"], n, body)
    for page in (1, 2):
        text = " ".join(["Question about pulmonary embolism imaging findings"] * 5)
        await as_tenant(runtime, ta, "INSERT INTO source_pages (tenant_id, source_id, page_no, "
                        "native_text) VALUES ($1,$2,$3,$4)", ta, ids["sp"], page, f"{page} {text}")


async def _notes_proof(deps: Any, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.worker.app.knowledge.pipeline import run_knowledge

    ta = ids["ta"]
    assert await run_knowledge(deps, ta, ids["sa"]) == "succeeded"
    assert await run_knowledge(deps, ta, ids["sa"]) == "skipped"
    concepts = {r["normalized_name"]: r for r in await as_tenant(
        runtime, ta, "SELECT id, normalized_name, aliases, curriculum_code FROM concepts")}
    uip = concepts["usual interstitial pneumonia"]
    assert "UIP" in uip["aliases"] and uip["curriculum_code"] == "CHEST"
    assert "honeycombing" in concepts
    claims = await as_tenant(runtime, ta, "SELECT evidence_span, status, citation FROM claims")
    assert len(claims) == 2 and {c["status"] for c in claims} == {"disputed"}
    for claim in claims:
        assert claim["evidence_span"] in CHUNK_A + CHUNK_B
        assert '"blocks"' in claim["citation"]
    conflicts = await as_tenant(runtime, ta, "SELECT kind, status FROM knowledge_conflicts")
    assert [(c["kind"], c["status"]) for c in conflicts] == [("numeric", "open")]
    assert len(await as_tenant(runtime, ta, "SELECT 1 FROM concept_edges")) == 1
    statuses = {r["status"] for r in await as_tenant(
        runtime, ta, "SELECT status FROM curriculum_mappings")}
    assert statuses == {"accepted", "review"}
    nodes = await as_tenant(runtime, ta, "SELECT curriculum_code, curriculum_node_id "
                            "FROM curriculum_mappings")
    assert all(r["curriculum_node_id"] == r["curriculum_code"] for r in nodes)  # system level
    for table in ("concepts", "claims", "knowledge_conflicts", "curriculum_mappings"):
        assert await as_tenant(runtime, ids["tb"], f"SELECT 1 FROM {table}") == [], table


async def _paper_proof(deps: Any, runtime: Any, ids: dict[str, UUID]) -> None:
    from apps.worker.app.ingest.db import tenant_tx
    from apps.worker.app.knowledge.papers import recompute_weights
    from apps.worker.app.knowledge.pipeline import run_knowledge

    ta = ids["ta"]
    assert await run_knowledge(deps, ta, ids["sp"], "past_paper") == "succeeded"
    freq = await as_tenant(runtime, ta, "SELECT curriculum_code, topic, count, exam_target, year "
                           "FROM topic_frequencies ORDER BY curriculum_code")
    assert [(r["curriculum_code"], r["count"], r["exam_target"], r["year"]) for r in freq] == [
        ("CHEST", 2, "imm", 2019), ("GI", 1, "imm", 2019)]
    # v3: a node below system level is the topic key; an invented id is dropped.
    assert [r["topic"] for r in freq] == ["CHEST.PULM_VASC.PE", "intussusception"]
    weights = await as_tenant(runtime, ta, "SELECT exam_target, approved FROM topic_weights")
    assert {r["exam_target"] for r in weights} == {"imm", "all"}
    assert not any(r["approved"] for r in weights)
    await as_tenant(runtime, ta, "UPDATE topic_weights SET approved = true, approved_at = now()")
    async with tenant_tx(deps.engine, ta) as session:
        await recompute_weights(session, ta, ids["ua"])  # unchanged -> approval kept
    assert all(r["approved"] for r in await as_tenant(
        runtime, ta, "SELECT approved FROM topic_weights"))
    await as_tenant(runtime, ta, "UPDATE topic_frequencies SET count = 5 "
                    "WHERE curriculum_code = 'GI'")
    async with tenant_tx(deps.engine, ta) as session:
        await recompute_weights(session, ta, ids["ua"])  # changed -> approval cleared
    gi = await as_tenant(runtime, ta, "SELECT approved FROM topic_weights "
                         "WHERE curriculum_code = 'GI' AND topic = '' AND exam_target = 'imm'")
    assert gi[0]["approved"] is False
    assert await as_tenant(runtime, ids["tb"], "SELECT 1 FROM topic_weights") == []


async def _run() -> None:
    from apps.worker.app.knowledge.runtime import KnowledgeDeps
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_dsn, runtime_dsn = require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await seed(admin)
    url = runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    transport = ScriptedTransport({"knowledge_extract": _extract, "topic_classify": _classify,
                                   "paper_topics": _paper})
    try:
        for source in ("sa", "sp"):
            await add_job(runtime, ids["ta"], ids[source])
        await _seed_content(runtime, ids)
        deps = KnowledgeDeps(engine=engine, transport=transport)
        await _notes_proof(deps, runtime, ids)
        assert transport.calls.count("knowledge_extract") == 2  # short chunk skipped, no rerun
        await _paper_proof(deps, runtime, ids)
    finally:
        await engine.dispose()
        await runtime.close()
        await cleanup(admin, ids)
        await admin.close()


def test_knowledge_pipeline_against_runtime_role() -> None:
    require_env()
    asyncio.run(_run())
