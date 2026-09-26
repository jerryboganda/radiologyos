"""Knowledge-graph writes (apps/worker/app/knowledge/graph.py) against a recording session.

The fake session records every statement and returns scripted rows, so the tests
check the decisions (merge vs create, duplicate vs conflict) and that a conflict
never overwrites a claim, without a database.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.worker.app.knowledge import graph
from packages.knowledge.curriculum import NodeMapping
from packages.knowledge.models import ExtractedClaim, ExtractedConcept, TopicMapping
from packages.knowledge.text import CANDIDATE, alias_keys, normalize_name

TENANT = UUID("20000000-0000-4000-8000-000000000001")
SOURCE = uuid4()
OTHER_SOURCE = uuid4()
META = {"source_id": SOURCE, "chunk_id": uuid4(), "page_from": 3, "page_to": 4,
        "agent": "knowledge_extract/v1", "unit": "chunk:abc"}
CITATION = {"source_id": str(SOURCE), "page_from": 3, "page_to": 4, "blocks": []}


class _Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> _Result:
        return self

    def __iter__(self) -> Any:
        return iter(self.value or [])

    def all(self) -> list[Any]:
        return list(self.value or [])

    def scalar_one(self) -> Any:
        return self.value


class Recorder:
    """Returns scripted results by SQL prefix, in order; records (sql, params)."""

    def __init__(self, script: dict[str, list[Any]] | None = None) -> None:
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = " ".join(str(statement).split())
        self.calls.append((sql, dict(params or {})))
        for prefix, queue in self.script.items():
            if sql.startswith(prefix) and queue:
                return _Result(queue.pop(0))
        return _Result(None)

    def matching(self, prefix: str) -> list[dict[str, Any]]:
        return [p for sql, p in self.calls if sql.startswith(prefix)]


def _concept(name: str, *aliases: str) -> ExtractedConcept:
    return ExtractedConcept(name=name, type="disease", aliases=list(aliases))


def _claim(text: str, span: str = "synthetic evidence span") -> ExtractedClaim:
    return ExtractedClaim(concept="Adrenal adenoma", type="imaging_finding", text=text,
                          evidence_span=span, importance=4, modality="MRI")


def _row(name: str, aliases: list[str], keys: list[str]) -> dict[str, Any]:
    return {"id": uuid4(), "name": name, "normalized_name": normalize_name(name),
            "aliases": aliases, "alias_keys": keys}


# ---- concept resolution ----------------------------------------------------------


async def test_new_concept_is_inserted_for_the_tenant() -> None:
    new_id = uuid4()
    session = Recorder({"SELECT": [[]], "INSERT": [new_id]})
    concept = _concept("  Pulmonary alveolar proteinosis ", "PAP", " ", "Alveolar lipoproteinosis")
    assert await graph.resolve_concept(session, TENANT, concept) == new_id  # type: ignore[arg-type]
    (lookup,) = session.matching("SELECT id, name")
    keys = alias_keys(concept.name, concept.aliases)
    assert lookup == {"keys": keys, "key": keys[0], "floor": CANDIDATE}
    (insert,) = session.matching("INSERT INTO concepts")
    assert insert["t"] == TENANT and insert["name"] == "Pulmonary alveolar proteinosis"
    assert insert["key"] == keys[0] and insert["keys"] == keys
    assert insert["aliases"] == ["PAP", "Alveolar lipoproteinosis"]
    assert session.matching("UPDATE") == []


async def test_alias_match_merges_and_records_new_aliases() -> None:
    existing = _row("Usual interstitial pneumonia", ["UIP"], ["usual interstitial pneumonia"])
    session = Recorder({"SELECT": [[existing]]})
    concept = _concept("Usual interstitial pneumonia", "UIP pattern")
    merged = await graph.resolve_concept(session, TENANT, concept)  # type: ignore[arg-type]
    assert merged == existing["id"]
    (update,) = session.matching("UPDATE concepts SET aliases")
    assert update["id"] == existing["id"]
    assert update["a"] == ["UIP", "UIP pattern"]
    assert update["k"] == ["usual interstitial pneumonia", normalize_name("UIP pattern")]
    assert session.matching("INSERT") == []


async def test_near_exact_name_merges_without_an_alias_hit() -> None:
    existing = _row("Pulmonary alveolar proteinosis", [], ["pulmonary alveolar proteinosis"])
    session = Recorder({"SELECT": [[existing]]})
    concept = _concept("Pulmonary alveolar proteinosis X")
    assert await graph.resolve_concept(session, TENANT, concept) == existing["id"]  # type: ignore[arg-type]
    (update,) = session.matching("UPDATE concepts")
    assert update["a"] == ["Pulmonary alveolar proteinosis X"]


async def test_review_band_similarity_creates_a_separate_concept() -> None:
    existing = _row("Pulmonary alveolar proteinosis", [], ["pulmonary alveolar proteinosis"])
    new_id = uuid4()
    session = Recorder({"SELECT": [[existing]], "INSERT": [new_id]})
    concept = _concept("Pulmonary alveola proteinosis")
    assert await graph.resolve_concept(session, TENANT, concept) == new_id  # type: ignore[arg-type]
    assert session.matching("UPDATE") == []


# ---- claims -----------------------------------------------------------------------


async def test_first_claim_is_inserted_with_its_citation() -> None:
    concept_id, claim_id = uuid4(), uuid4()
    session = Recorder({"SELECT": [[]], "INSERT": [claim_id]})
    claim = _claim("  Lipid-rich adenoma drops signal on opposed-phase MRI  ")
    outcome = await graph.store_claim(session, TENANT, concept_id, claim, CITATION, META)  # type: ignore[arg-type]
    assert outcome == "inserted"
    (lookup,) = session.matching("SELECT id, statement")
    assert lookup == {"c": concept_id}
    assert "status IN ('active', 'disputed')" in session.calls[0][0]
    (insert,) = session.matching("INSERT INTO claims")
    assert insert["t"] == TENANT and insert["c"] == concept_id
    assert insert["statement"] == "Lipid-rich adenoma drops signal on opposed-phase MRI"
    assert json.loads(insert["citation"]) == CITATION
    assert (insert["s"], insert["chunk"], insert["pf"], insert["pt"], insert["agent"]) == (
        SOURCE, META["chunk_id"], 3, 4, "knowledge_extract/v1")


DUPLICATE = "Honeycombing is the hallmark of usual interstitial pneumonia on HRCT"


@pytest.mark.parametrize(("source", "supports"), [(OTHER_SOURCE, 1), (SOURCE, 0)])
async def test_duplicate_claim_merges_and_adds_support_only_from_another_source(
    source: UUID, supports: int
) -> None:
    existing = {"id": uuid4(), "statement": DUPLICATE + ".", "source_id": source}
    session = Recorder({"SELECT": [[existing]]})
    outcome = await graph.store_claim(  # type: ignore[arg-type]
        session, TENANT, uuid4(), _claim(DUPLICATE), CITATION, META)
    assert outcome == "merged"
    updates = session.matching("UPDATE claims SET supporting")
    assert len(updates) == supports
    if supports:
        assert updates[0]["id"] == existing["id"]
        assert json.loads(updates[0]["c"]) == [CITATION]
    assert session.matching("INSERT") == []


async def test_contradiction_records_a_conflict_and_disputes_both_claims() -> None:
    concept_id, new_id = uuid4(), uuid4()
    old = {"id": uuid4(), "statement": "Lipid-poor adrenal adenoma shows signal drop on "
           "opposed-phase MRI", "source_id": OTHER_SOURCE}
    session = Recorder({"SELECT": [[old]], "INSERT INTO claims": [new_id]})
    claim = _claim("Lipid-poor adrenal adenoma shows no signal drop on opposed-phase MRI")
    outcome = await graph.store_claim(session, TENANT, concept_id, claim, CITATION, META)  # type: ignore[arg-type]
    assert outcome == "conflict"
    (conflict,) = session.matching("INSERT INTO knowledge_conflicts")
    assert conflict["t"] == TENANT and conflict["c"] == concept_id
    assert (conflict["a"], conflict["b"], conflict["k"]) == (old["id"], new_id, "negation")
    (disputed,) = session.matching("UPDATE claims SET status = 'disputed'")
    assert disputed == {"a": old["id"], "b": new_id}
    assert not any("statement =" in sql or "DELETE" in sql for sql, _ in session.calls)
    order = [sql.split(" (")[0] for sql, _ in session.calls]
    assert order.index("INSERT INTO claims") < order.index("INSERT INTO knowledge_conflicts")


async def test_every_contradicted_claim_gets_its_own_conflict_row() -> None:
    new_id = uuid4()
    rows = [{"id": uuid4(), "statement": f"The normal common bile duct diameter is up to {n} mm"
             " in adults", "source_id": OTHER_SOURCE} for n in (6, 7)]
    session = Recorder({"SELECT": [rows], "INSERT INTO claims": [new_id]})
    claim = _claim("The normal common bile duct diameter is up to 8 mm in adults")
    assert await graph.store_claim(session, TENANT, uuid4(), claim, CITATION, META) == "conflict"  # type: ignore[arg-type]
    conflicts = session.matching("INSERT INTO knowledge_conflicts")
    assert [c["a"] for c in conflicts] == [r["id"] for r in rows]
    assert all(c["b"] == new_id and c["k"] == "numeric" for c in conflicts)
    assert all(len(c["d"]) <= 1000 for c in conflicts)
    assert len(session.matching("UPDATE claims SET status")) == 2


async def test_unrelated_existing_claim_is_left_untouched() -> None:
    other = {"id": uuid4(), "statement": "Sarcoidosis shows perilymphatic nodules",
             "source_id": OTHER_SOURCE}
    session = Recorder({"SELECT": [[other]], "INSERT": [uuid4()]})
    claim = _claim("Pulmonary alveolar proteinosis shows crazy paving")
    assert await graph.store_claim(session, TENANT, uuid4(), claim, CITATION, META) == "inserted"  # type: ignore[arg-type]
    assert session.matching("UPDATE") == [] and session.matching("INSERT INTO knowledge") == []


# ---- edges and mappings ----------------------------------------------------------------


async def test_edge_is_written_once_and_self_loops_are_skipped() -> None:
    session = Recorder()
    a, b = uuid4(), uuid4()
    await graph.store_edge(session, TENANT, a, a, "sign_of", CITATION, META)  # type: ignore[arg-type]
    assert session.calls == []
    await graph.store_edge(session, TENANT, a, b, "sign_of", CITATION, META)  # type: ignore[arg-type]
    (sql, params), = session.calls
    assert sql.startswith("INSERT INTO concept_edges") and "ON CONFLICT DO NOTHING" in sql
    assert (params["t"], params["a"], params["b"], params["r"]) == (TENANT, a, b, "sign_of")
    assert json.loads(params["c"]) == CITATION and params["s"] == SOURCE


async def test_accepted_mapping_tags_concepts_only_when_more_confident() -> None:
    session = Recorder()
    ids = [uuid4(), uuid4()]
    mapping = TopicMapping(curriculum_code="CHEST", topic="  pulmonary embolism ", confidence=0.9)
    meta = {**META, "agent": "topic_classify/v1"}
    await graph.store_mapping(session, TENANT, mapping, "accepted", ids, meta)  # type: ignore[arg-type]
    (insert,) = session.matching("INSERT INTO curriculum_mappings")
    assert insert["t"] == TENANT and insert["u"] == "chunk:abc"
    assert (insert["code"], insert["node"], insert["status"]) == ("CHEST", "CHEST", "accepted")
    assert insert["topic"] == "pulmonary embolism" and insert["agent"] == "topic_classify/v1"
    (tagged,) = session.matching("UPDATE concepts SET curriculum_code")
    assert tagged == {"code": "CHEST", "conf": 0.9, "ids": ids}
    assert "curriculum_confidence, 0) < :conf" in session.calls[-1][0]


@pytest.mark.parametrize(("status", "ids"), [("review", [uuid4()]), ("accepted", [])])
async def test_review_or_conceptless_mapping_never_tags_concepts(
    status: str, ids: list[UUID]
) -> None:
    session = Recorder()
    node = NodeMapping("NEURO", "NEURO.STROKE", status)
    await graph.store_node_mapping(session, TENANT, node, "stroke", 0.5, ids, META)  # type: ignore[arg-type]
    (insert,) = session.matching("INSERT INTO curriculum_mappings")
    assert (insert["code"], insert["node"], insert["status"]) == ("NEURO", "NEURO.STROKE", status)
    assert session.matching("UPDATE") == []
