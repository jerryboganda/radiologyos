"""Cloze cards from claims and image cards from figures (ADR 0029): rules and routes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import study
from apps.api.app.main import app
from apps.api.app.schemas.study import CardOut
from apps.api.app.security.principal import Principal
from apps.api.tests.study_fakes import MemoryStudyRepo
from fastapi.testclient import TestClient
from packages.study.knowledge_cards import (
    BLANK,
    blank,
    card_code,
    claim_citation,
    cloze_card,
    image_card,
    key_term,
)

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
USER = UUID("10000000-0000-4000-8000-000000000001")
OTHER = UUID("10000000-0000-4000-8000-000000000002")
TENANT = UUID("20000000-0000-4000-8000-000000000001")
SYSTEMS = frozenset({"CHEST", "NEURO"})


def claim(**overrides: Any) -> dict[str, Any]:
    return {"id": uuid4(), "concept_id": uuid4(), "concept_name": "Pulmonary alveolar proteinosis",
            "aliases": ["PAP"], "concept_code": "CHEST.ILD", "mapped_code": None,
            "statement": "Pulmonary alveolar proteinosis shows crazy paving on HRCT.",
            "evidence_span": "crazy  paving on HRCT", "source_id": uuid4(),
            "source_title": "Synthetic chest", "chunk_id": uuid4(), "page_from": 4, "page_to": 5,
            "citation": {"blocks": [{"page_no": 4, "block_no": 2, "bbox": [0.1, 0.2, 0.5, 0.3]}]},
            **overrides}


def figure(**overrides: Any) -> dict[str, Any]:
    return {"id": uuid4(), "source_id": uuid4(), "source_title": "Synthetic chest",
            "page_no": 7, "caption": "Fig 2. Crazy paving in PAP", "description":
            "Geographic ground-glass with septal thickening.", "modality": "CT",
            "anatomy": "chest", "findings": ["crazy paving"], "bbox": [0.1, 0.1, 0.9, 0.8],
            "mapped_code": "NEURO", **overrides}


def test_key_term_prefers_the_longest_named_term_then_a_measurement() -> None:
    statement = "In PAP, pulmonary alveolar proteinosis gives crazy paving."
    assert key_term(statement, ["PAP", "Pulmonary alveolar proteinosis"]) == \
        "pulmonary alveolar proteinosis"
    assert key_term("A pneumothorax over 2 cm needs aspiration.", ["tension"]) == "2 cm"
    assert key_term("Septal lines are seen.", ["PAP"]) is None
    assert key_term("PAPillary change", ["PAP"]) is None  # word boundaries only


def test_blank_hides_every_occurrence_and_needs_context() -> None:
    front = blank("PAP is rare; PAP shows crazy paving.", "PAP")
    assert front == f"{BLANK} is rare; {BLANK} shows crazy paving."
    assert blank("PAP", "PAP") is None
    assert blank("pap shows crazy paving", "PAP") == f"{BLANK} shows crazy paving"


def test_cloze_card_cites_the_claim_evidence_blocks() -> None:
    row = claim()
    card = cloze_card(row, SYSTEMS)
    assert card is not None
    assert "pulmonary alveolar proteinosis" not in card["front"].lower() and BLANK in card["front"]
    assert card["back"].startswith("Pulmonary alveolar proteinosis")
    assert "crazy paving on HRCT" in card["back"]
    assert (card["card_type"], card["origin"], card["claim_id"]) == ("cloze", "claim", row["id"])
    citation = card["citation"]
    assert citation["kind"] == "claim" and citation["claim_id"] == str(row["id"])
    assert citation["source_id"] == str(row["source_id"])
    assert (citation["page_from"], citation["page_to"]) == (4, 5)
    assert citation["block_refs"] == [{"page": 4, "block": 2}]
    assert card["curriculum_code"] == "CHEST"


def test_cloze_card_fails_closed_without_term_or_provenance() -> None:
    assert cloze_card(claim(statement="Septal lines appear early.", aliases=[]), SYSTEMS) is None
    assert cloze_card(claim(source_id=None, citation={}), SYSTEMS) is None
    assert claim_citation(claim(page_from=None)) is None


def test_card_code_falls_back_to_unmapped() -> None:
    assert card_code("CHEST.PULM_VASC.PE", SYSTEMS) == "CHEST"
    assert card_code("ABDO", SYSTEMS) == "UNMAPPED" and card_code(None, SYSTEMS) == "UNMAPPED"


def test_image_card_hides_the_caption_and_cites_the_figure() -> None:
    row = figure()
    card = image_card(row, SYSTEMS)
    assert card is not None
    assert "PAP" not in card["front"] and "(CT chest)" in card["front"]
    assert card["back"].startswith("Fig 2. Crazy paving in PAP")
    assert "Findings: crazy paving" in card["back"]
    assert (card["card_type"], card["figure_id"], card["curriculum_code"]) == \
        ("image", row["id"], "NEURO")
    citation = card["citation"]
    assert citation["kind"] == "figure" and citation["figure_id"] == str(row["id"])
    assert (citation["page_from"], citation["page_to"]) == (7, 7)
    assert citation["bbox"] == [0.1, 0.1, 0.9, 0.8]
    assert image_card(figure(description="  "), SYSTEMS) is None
    assert image_card(figure(page_no=None), SYSTEMS) is None


def test_card_out_links_image_cards_to_the_signed_media_route() -> None:
    fig = uuid4()
    base = {"id": uuid4(), "curriculum_code": "CHEST", "topic": "t", "front": "f", "back": "b",
            "origin": "figure", "card_type": "image", "figure_id": fig,
            "citation": {"kind": "figure", "source_id": uuid4(), "source_title": "S",
                         "page_from": 1, "page_to": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
            "state": "new", "stability": 0, "difficulty": 0, "due_at": NOW,
            "last_review_at": None, "reps": 0, "lapses": 0}
    out = CardOut.model_validate(base)
    assert out.figure_image_path == f"/v1/library/figures/{fig}/image"
    assert CardOut.model_validate({**base, "figure_id": None}).figure_image_path is None


class KnowledgeRepo(MemoryStudyRepo):
    """Adds per-user claim and figure candidates to the in-memory study repo."""

    def __init__(self) -> None:
        super().__init__()
        self.claims: list[tuple[UUID, dict[str, Any]]] = []
        self.figures: list[tuple[UUID, dict[str, Any]]] = []

    async def cloze_candidates(self, user_id: UUID, source_id: UUID | None, topic: str | None,
                               limit: int) -> list[dict[str, Any]]:
        carded = {card.get("claim_id") for owner, card in self.cards.values() if owner == user_id}
        return [c for owner, c in self.claims if owner == user_id and c["id"] not in carded][:limit]

    async def figure_candidates(self, user_id: UUID, source_id: UUID | None,
                                topic: str | None, limit: int) -> list[dict[str, Any]]:
        carded = {card.get("figure_id") for owner, card in self.cards.values()
                  if owner == user_id}
        return [f for owner, f in self.figures
                if owner == user_id and f["id"] not in carded][:limit]

    async def insert_knowledge_card(self, user_id: UUID,
                                    card: dict[str, Any]) -> dict[str, Any] | None:
        return await self.insert_card(user_id, card)


@pytest.fixture
def repo() -> Iterator[KnowledgeRepo]:
    memory = KnowledgeRepo()
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.principal_context] = lambda: Principal(USER, TENANT)
    app.dependency_overrides[study.get_now] = lambda: NOW
    yield memory
    app.dependency_overrides.clear()


def test_route_requires_identity() -> None:
    response = TestClient(app).post("/v1/study/cards/from-knowledge", json={"kind": "cloze"})
    assert response.status_code == 401


def test_route_makes_cloze_cards_once_and_only_from_own_claims(repo: KnowledgeRepo) -> None:
    repo.claims = [(USER, claim()), (USER, claim(statement="Nothing to blank here.",
                                                  aliases=[])), (OTHER, claim())]
    client = TestClient(app)
    body = client.post("/v1/study/cards/from-knowledge", json={"kind": "cloze"}).json()
    assert (len(body["created"]), body["skipped"], body["considered"]) == (1, 1, 2)
    card = body["created"][0]
    assert card["card_type"] == "cloze" and card["citation"]["kind"] == "claim"
    again = client.post("/v1/study/cards/from-knowledge", json={"kind": "cloze"}).json()
    assert again["created"] == [] and again["considered"] == 1


def test_route_makes_image_cards_with_a_media_link(repo: KnowledgeRepo) -> None:
    repo.figures = [(USER, figure()), (OTHER, figure())]
    body = TestClient(app).post("/v1/study/cards/from-knowledge",
                                json={"kind": "image", "max_cards": 5}).json()
    assert len(body["created"]) == 1
    card = body["created"][0]
    assert card["figure_image_path"].startswith("/v1/library/figures/")
    assert card["citation"]["bbox"] == [0.1, 0.1, 0.9, 0.8]


def test_route_validates_input(repo: KnowledgeRepo) -> None:
    client = TestClient(app)
    assert client.post("/v1/study/cards/from-knowledge", json={"kind": "basic"}).status_code \
        == 422
    assert client.post("/v1/study/cards/from-knowledge",
                       json={"kind": "cloze", "max_cards": 51}).status_code == 422
