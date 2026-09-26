"""Notes-mode knowledge extraction (apps/worker/app/knowledge/notes.py) with fakes.

Database helpers, graph writes, and the model call are replaced by recorders,
so the tests check unit keys, resumability, deferral, the per-run budget,
tenant scoping, and what the prompts carry. Synthetic text only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.worker.app.knowledge import db, notes
from apps.worker.app.knowledge.runtime import Deferred, KnowledgeDeps
from packages.knowledge.curriculum import prompt_listing
from packages.knowledge.models import KnowledgeExtraction, TopicClassification
from packages.library.quality import MIN_EVIDENCE_CLAIMS
from packages.models.claude_code import ModelCall, ModelResult, UsageLimitError
from packages.models.gateway import load_agent

TENANT = UUID("20000000-0000-4000-8000-000000000001")
SOURCE = {"id": uuid4(), "title": "Synthetic chest notes"}
VERSION = 3
TEXT = (
    "Usual interstitial pneumonia (UIP) shows basal, subpleural reticulation with "
    "honeycombing and traction bronchiectasis on HRCT. Ground-glass opacity is not a "
    "dominant feature of UIP. Honeycombing indicates established fibrosis and the pattern "
    "is typically seen in idiopathic pulmonary fibrosis in older adults."
)
GOOD_SPAN = "traction bronchiectasis on HRCT"
EXTRACTION = KnowledgeExtraction.model_validate({
    "concepts": [{"name": "Usual interstitial pneumonia", "type": "disease", "aliases": ["UIP"]},
                 {"name": "Honeycombing", "type": "sign", "aliases": []}],
    "claims": [
        {"concept": "Usual interstitial pneumonia", "type": "imaging_finding",
         "text": "UIP shows traction bronchiectasis.", "evidence_span": GOOD_SPAN,
         "importance": 4, "modality": "HRCT"},
        {"concept": "Usual interstitial pneumonia", "type": "imaging_finding",
         "text": "Invented.", "evidence_span": "upper lobe predominance is typical",
         "importance": 2, "modality": "HRCT"},
    ],
    "relations": [{"src": "Honeycombing", "dst": "Usual interstitial pneumonia",
                   "relation": "sign_of"}],
})
TOPICS = TopicClassification.model_validate({"topics": [
    {"curriculum_code": "MADE_UP", "topic": "nothing", "confidence": 0.99},
    {"curriculum_code": "CHEST", "topic": "interstitial lung disease", "confidence": 0.9},
    {"curriculum_code": "CHEST", "topic": "fibrosis", "confidence": 0.4},
]})


def _chunk(text: str = TEXT, heading: str | None = "Chest > ILD") -> dict[str, Any]:
    return {"id": uuid4(), "chunk_no": 0, "page_from": 7, "page_to": 8, "heading": heading,
            "text": text, "block_refs": []}


@dataclass
class World:
    chunks: list[dict[str, Any]] = field(default_factory=list)
    done: set[str] = field(default_factory=set)
    runs: list[tuple[str, str, str | None]] = field(default_factory=list)
    txs: list[UUID] = field(default_factory=list)
    open_txs: int = 0
    writes: list[tuple[str, Any]] = field(default_factory=list)
    model: list[tuple[str, str, int]] = field(default_factory=list)
    replies: dict[str, Callable[[], Any]] = field(default_factory=dict)


@dataclass
class Tx:
    tenant: UUID


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()
    w.replies = {"knowledge_extract": lambda: EXTRACTION, "topic_classify": lambda: TOPICS}

    @asynccontextmanager
    async def fake_tx(engine: Any, tenant_id: UUID) -> AsyncIterator[Tx]:
        assert engine == "engine"
        w.txs.append(tenant_id)
        w.open_txs += 1
        try:
            yield Tx(tenant_id)
        finally:
            w.open_txs -= 1

    async def chunks(session: Tx, source_id: UUID) -> list[dict[str, Any]]:
        assert session.tenant == TENANT and source_id == SOURCE["id"]
        return w.chunks

    async def run_done(session: Tx, source_id: UUID, unit: str, agent: str, v: int) -> bool:
        assert (session.tenant, agent, v) == (TENANT, notes.EXTRACT, VERSION)
        return unit in w.done

    async def record_run(session: Tx, tenant: UUID, source_id: UUID, unit: str, agent: str,
                         v: int, status: str, out: str | None = None) -> None:
        assert session.tenant == tenant == TENANT and (agent, v) == (notes.EXTRACT, VERSION)
        w.runs.append((unit, status, out))
        if status == "succeeded":
            w.done.add(unit)

    async def blocks(session: Tx, source_id: UUID, a: int, b: int) -> list[dict[str, Any]]:
        return [{"page_no": 7, "block_no": 2, "text": TEXT[:120], "bbox": [0, 0, 1, 1]}]

    def call_agent(deps: Any, name: str, prompt: str, accept: Any = None) -> Any:
        w.model.append((name, prompt, w.open_txs))
        return w.replies[name]()

    monkeypatch.setattr(notes, "tenant_tx", fake_tx)
    monkeypatch.setattr(notes, "call_agent", call_agent)
    for name, fn in (("chunks", chunks), ("run_done", run_done), ("record_run", record_run),
                     ("blocks_for_pages", blocks)):
        monkeypatch.setattr(notes.db, name, fn)
    _record_graph(monkeypatch, w)
    return w


def _record_graph(monkeypatch: pytest.MonkeyPatch, w: World) -> None:
    async def resolve(session: Tx, tenant: UUID, concept: Any) -> UUID:
        assert session.tenant == tenant == TENANT
        w.writes.append(("concept", concept.name))
        return UUID(int=len(w.writes))

    def recorder(kind: str) -> Callable[..., Any]:
        async def write(session: Tx, tenant: UUID, *args: Any) -> str:
            assert session.tenant == tenant == TENANT
            w.writes.append((kind, args))
            return "inserted"
        return write

    monkeypatch.setattr(notes.graph, "resolve_concept", resolve)
    for kind in ("store_claim", "store_edge", "store_mapping"):
        monkeypatch.setattr(notes.graph, kind, recorder(kind))


DEPS = KnowledgeDeps(engine="engine", transport=None)  # type: ignore[arg-type]


async def _run(w: World) -> str:
    return await notes.run_notes(DEPS, TENANT, SOURCE, VERSION)


def _kinds(w: World) -> list[str]:
    return [kind for kind, _ in w.writes]


async def test_chunk_under_min_words_is_skipped_without_a_model_call(world: World) -> None:
    world.chunks = [_chunk(" ".join(["word"] * (notes.MIN_WORDS - 1)))]
    assert await _run(world) == "chunks:0,claims:0,rejected:0,failed:0"
    assert world.model == [] and world.runs == [] and world.txs == [TENANT]


async def test_chunk_is_extracted_filtered_persisted_and_recorded(world: World) -> None:
    chunk = _chunk()
    world.chunks = [chunk]
    assert await _run(world) == "chunks:1,claims:1,rejected:1,failed:0"
    assert [name for name, _, _ in world.model] == ["knowledge_extract", "topic_classify"]
    assert _kinds(world) == ["concept", "concept", "store_claim", "store_edge",
                             "store_mapping", "store_mapping"]
    concept_id, claim, citation, meta = world.writes[2][1]
    assert claim.evidence_span == GOOD_SPAN and concept_id == UUID(int=1)
    assert citation["source_id"] == str(SOURCE["id"]) and citation["chunk_id"] == str(chunk["id"])
    assert (citation["page_from"], citation["page_to"]) == (7, 8)
    assert citation["blocks"] and citation["blocks"][0]["block_no"] == 2
    assert meta["agent"] == notes.EXTRACT and meta["unit"] == f"chunk:{db.unit_hash(TEXT)}"
    src, dst, relation, edge_citation, _ = world.writes[3][1]
    assert (src, dst, relation) == (UUID(int=2), UUID(int=1), "sign_of")
    assert edge_citation["blocks"] == []
    first, second = world.writes[4][1], world.writes[5][1]
    assert (first[0].topic, first[1], first[2]) == ("interstitial lung disease", "accepted",
                                                    [UUID(int=1), UUID(int=2)])
    assert (second[1], second[2], second[3]["agent"]) == ("review", [], notes.CLASSIFY)
    assert world.runs == [(f"chunk:{db.unit_hash(TEXT)}", "succeeded", "claims:1,rej:1")]


async def test_every_transaction_is_tenant_scoped_and_none_spans_a_model_call(
    world: World,
) -> None:
    world.chunks = [_chunk(), _chunk(TEXT + " Extra synthetic words.")]
    await _run(world)
    assert world.txs and set(world.txs) == {TENANT}
    assert all(open_txs == 0 for _, _, open_txs in world.model)


async def test_done_units_and_identical_rechunked_text_are_not_re_extracted(
    world: World,
) -> None:
    world.chunks = [_chunk(), _chunk()]  # same text, different chunk ids
    assert await _run(world) == "chunks:2,claims:1,rejected:1,failed:0"
    assert len([m for m in world.model if m[0] == "knowledge_extract"]) == 1
    world.model.clear()
    assert await _run(world) == "chunks:2,claims:0,rejected:0,failed:0"
    assert world.model == [] and len(world.runs) == 1


async def test_model_failure_is_recorded_and_retried_on_the_next_run(world: World) -> None:
    world.chunks = [_chunk()]
    world.replies["knowledge_extract"] = lambda: None
    assert await _run(world) == "chunks:1,claims:0,rejected:0,failed:1"
    assert world.runs == [(f"chunk:{db.unit_hash(TEXT)}", "failed", "model_error")]
    assert [n for n, _, _ in world.model] == ["knowledge_extract"] and world.writes == []
    world.replies["knowledge_extract"] = lambda: EXTRACTION
    assert await _run(world) == "chunks:1,claims:1,rejected:1,failed:0"


async def test_failed_classification_still_stores_knowledge(world: World) -> None:
    world.chunks = [_chunk()]
    world.replies["topic_classify"] = lambda: None
    await _run(world)
    assert "store_mapping" not in _kinds(world) and "store_claim" in _kinds(world)
    assert world.runs[0][1] == "succeeded"


@pytest.mark.parametrize("agent", ["knowledge_extract", "topic_classify"])
async def test_usage_limit_defers_and_leaves_the_unit_resumable(
    world: World, agent: str
) -> None:
    first, second = _chunk(), _chunk(TEXT + " A different synthetic tail.")
    world.chunks = [first, second]
    calls = {"n": 0}
    normal = world.replies[agent]

    def limited() -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise Deferred
        return normal()

    world.replies[agent] = limited
    with pytest.raises(Deferred):
        await _run(world)
    assert [unit for unit, _, _ in world.runs] == [f"chunk:{db.unit_hash(first['text'])}"]
    assert _kinds(world).count("store_claim") == 1


async def test_run_budget_requeues_after_units_per_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notes, "UNITS_PER_RUN", 2)
    world.chunks = [_chunk(TEXT + f" tail {n}") for n in range(3)]
    with pytest.raises(notes.Continue):
        await _run(world)
    assert len(world.runs) == 2
    assert await _run(world) == "chunks:3,claims:1,rejected:1,failed:0"
    assert len(world.runs) == 3


async def test_done_units_do_not_consume_the_run_budget(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notes, "UNITS_PER_RUN", 1)
    world.chunks = [_chunk(TEXT + f" tail {n}") for n in range(3)]
    world.done = {f"chunk:{db.unit_hash(c['text'])}" for c in world.chunks[:2]}
    assert await _run(world) == "chunks:3,claims:1,rejected:1,failed:0"


async def test_prompts_carry_only_labelled_data(world: World) -> None:
    world.chunks = [_chunk(heading=None)]
    await _run(world)
    (_, extract, _), (_, classify, _) = world.model
    residue = extract.replace(SOURCE["title"], "").replace(TEXT, "").replace("7-8", "")
    assert residue.split() == ["Source", "title:", "Heading", "path:", "(none)", "Pages:",
                               "Chunk", "text:"]
    assert prompt_listing() in classify and TEXT in classify
    assert "Usual interstitial pneumonia, Honeycombing" in classify
    for name, prompt in (("knowledge_extract", extract), ("topic_classify", classify)):
        system = load_agent(name).prompt.system_prompt
        assert system.strip() and system.strip()[:80] not in prompt


def test_accept_gate_rejects_mostly_unsupported_extractions() -> None:
    unsupported = EXTRACTION.claims[1]
    bad = EXTRACTION.model_copy(update={"claims": [unsupported] * MIN_EVIDENCE_CLAIMS})
    assert notes._evidence_problem(bad, TEXT) == "unsupported_claims"
    assert notes._evidence_problem(EXTRACTION, TEXT) is None


class _Transport:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return ModelResult(output=EXTRACTION.model_dump(), duration_ms=1, cost_usd=0.0)


async def test_real_call_agent_uses_the_versioned_system_prompt_and_defers(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.worker.app.knowledge import runtime

    monkeypatch.setattr(notes, "call_agent", runtime.call_agent)
    world.chunks = [_chunk()]
    limited = _Transport(UsageLimitError("window"))
    with pytest.raises(Deferred):
        await notes.run_notes(KnowledgeDeps("engine", limited), TENANT, SOURCE, VERSION)  # type: ignore[arg-type]
    assert world.runs == [] and world.writes == []
    call = limited.calls[0]
    assert call.system_prompt == load_agent("knowledge_extract").prompt.system_prompt
    assert TEXT in call.user_prompt and call.system_prompt not in call.user_prompt
