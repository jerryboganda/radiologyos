"""Knowledge-graph expansion of tutor context (ADR 0028): bounds and citation integrity."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from apps.api.app.tutor import graph as graph_sql
from packages.tutor.graph import (
    DEFAULT_BUDGET,
    GraphBudget,
    budget_for,
    pick_neighbours,
    select_claims,
)
from packages.tutor.grounding import excerpts_from_hits, ground_sources
from packages.tutor.models import LayoutAnswer, SourceAnswer

SEED, OTHER, DDX, FAR = uuid4(), uuid4(), uuid4(), uuid4()
TOP_CHUNK = uuid4()


def _claim(concept: UUID, span: str, **extra: Any) -> dict[str, Any]:
    row = {"id": uuid4(), "concept_id": concept, "concept_name": f"C-{str(concept)[:4]}",
           "evidence_span": span, "source_id": uuid4(), "source_title": "Synthetic deck",
           "chunk_id": uuid4(), "page_from": 3, "page_to": 3, "verification": "single_source",
           "importance": 3,
           "citation": {"blocks": [{"page_no": 3, "block_no": 2, "bbox": [0.1, 0.2, 0.3, 0.4]}]}}
    row.update(extra)
    return row


def test_neighbours_prefer_intent_relations_and_exclude_seeds() -> None:
    edges = [
        {"from_concept": SEED, "to_concept": OTHER, "relation": "associated_with"},
        {"from_concept": DDX, "to_concept": SEED, "relation": "differential_of"},
        {"from_concept": SEED, "to_concept": SEED, "relation": "is_a"},
        {"from_concept": OTHER, "to_concept": FAR, "relation": "differential_of"},
    ]
    ddx = pick_neighbours(edges, [SEED], "ddx", 5)
    assert [n.concept_id for n in ddx] == [DDX, OTHER]  # FAR is 2 hops away
    assert ddx[0].relation == "differential_of" and ddx[0].seed_id == SEED
    assert [n.concept_id for n in pick_neighbours(edges, [SEED], "ddx", 1)] == [DDX]


def test_claims_are_bounded_per_concept_and_in_total() -> None:
    rows = [_claim(SEED, f"seed fact {i}") for i in range(5)]
    rows += [_claim(DDX, f"ddx fact {i}") for i in range(5)]
    budget = GraphBudget(claims=3, per_concept=2)
    picked = select_claims(rows, [SEED], pick_neighbours(
        [{"from_concept": SEED, "to_concept": DDX, "relation": "differential_of"}],
        [SEED], "ddx", 4), budget, set(), {SEED: "Crazy paving"})
    assert [e.label for e in picked] == ["K1", "K2", "K3"]
    assert [e.text for e in picked] == ["seed fact 0", "seed fact 1", "ddx fact 0"]
    assert picked[2].heading.endswith("(differential of Crazy paving)")
    assert budget_for("quiz").claims == 0 and budget_for("explain") == DEFAULT_BUDGET


def test_claims_without_evidence_reference_are_never_offered() -> None:
    rows = [
        _claim(SEED, "no chunk", chunk_id=None),
        _claim(SEED, "   "),
        _claim(SEED, "no page", page_from=None),
        _claim(SEED, "already retrieved", chunk_id=TOP_CHUNK),
        _claim(SEED, "x" * 2000, verification="verified"),
        _claim(SEED, "duplicate"), _claim(SEED, "Duplicate"),
    ]
    picked = select_claims(rows, [SEED], [], GraphBudget(per_concept=5), {TOP_CHUNK}, {})
    assert [e.text[:9] for e in picked] == ["x" * 9, "duplicate"]
    assert len(picked[0].text) == DEFAULT_BUDGET.span_chars  # verified first, span bounded
    citation = picked[0].citation()
    assert citation.chunk_id == rows[4]["chunk_id"] and citation.page_from == 3
    assert citation.block_refs == [{"page_no": 3, "block_no": 2}]


def test_k_labels_ground_to_their_evidence_and_layout_is_kept() -> None:
    claim = select_claims([_claim(SEED, "Oedema also causes crazy paving.")], [SEED], [],
                          DEFAULT_BUDGET, set(), {})
    excerpts = [*excerpts_from_hits([{"id": TOP_CHUNK, "source_id": uuid4(),
                                      "source_title": "Deck", "page_from": 1, "page_to": 1,
                                      "heading": "", "text": "PAP.", "block_refs": []}]),
                *claim]
    answer = LayoutAnswer.model_validate({"coverage": "full", "segments": [
        {"text": "Oedema.", "sources": ["K1"], "row": "Pulmonary oedema",
         "column": "Discriminating features"},
        {"text": "PAP.", "sources": ["S1"], "section": "Findings", "row": "orphan"},
        {"text": "Made up.", "sources": ["K9"]},
    ]})
    kept, dropped = ground_sources(answer, excerpts)
    assert dropped == 1  # K9 was never supplied
    assert kept[0].citations[0].chunk_id == claim[0].chunk_id
    assert (kept[0].row, kept[0].column) == ("Pulmonary oedema", "Discriminating features")
    assert kept[1].section == "Findings" and kept[1].row is None  # a row needs a column
    plain, _ = ground_sources(SourceAnswer.model_validate(
        {"coverage": "full", "segments": [{"text": "PAP.", "sources": ["S1"]}]}), excerpts)
    assert plain[0].section is None and plain[0].row is None


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self.rows


class _Session:
    def __init__(self, seeds: list[dict[str, Any]], edges: list[dict[str, Any]],
                 claims: list[dict[str, Any]]) -> None:
        self.data = {"array_position": seeds, "concept_edges": edges, "row_number": claims}
        self.sql: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Rows:
        sql = str(statement)
        self.sql.append((sql, params))
        return _Rows(next(v for k, v in self.data.items() if k in sql))


async def test_expand_scopes_every_read_to_the_callers_sources() -> None:
    user = uuid4()
    session = _Session([{"id": SEED, "name": "Crazy paving"}],
                       [{"from_concept": SEED, "to_concept": DDX, "relation": "differential_of"}],
                       [_claim(SEED, "Seed fact."), _claim(DDX, "Neighbour fact.")])
    chunks = [TOP_CHUNK, *(uuid4() for _ in range(6))]
    out = await graph_sql.expand(session, user, chunks, "ddx")  # type: ignore[arg-type]
    assert [e.label for e in out] == ["K1", "K2"]
    assert len(session.sql) == 3
    for sql, params in session.sql:
        assert "s.uploaded_by = :u" in sql and "s.deleted_at IS NULL" in sql
        assert params["u"] == user
    assert session.sql[0][1]["ids"] == chunks[:4]  # only the top chunks seed the graph
    assert "status = 'active'" in session.sql[2][0]


async def test_expand_does_nothing_for_a_quiz_or_without_seeds() -> None:
    empty = _Session([], [], [])
    assert await graph_sql.expand(empty, uuid4(), [TOP_CHUNK], "quiz") == []  # type: ignore[arg-type]
    assert await graph_sql.expand(empty, uuid4(), [TOP_CHUNK], "explain") == []  # type: ignore[arg-type]
    assert len(empty.sql) == 1
