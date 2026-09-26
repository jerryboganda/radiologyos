"""Tutor intent routing, graph claims, and quiz hand-off over HTTP (ADR 0028)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from apps.api.app.main import app
from apps.api.tests.tutor_fakes import CHUNK, FIGURE_HIT, FakeTransport, tutor_env
from fastapi.testclient import TestClient
from packages.tutor.grounding import Excerpt

client = TestClient(app)
CLAIM = Excerpt(label="K1", chunk_id=uuid4(), source_id=uuid4(), source_title="Synthetic deck",
                page_from=9, page_to=9, heading="Knowledge graph: Pulmonary oedema",
                text="Pulmonary oedema can cause crazy paving.",
                block_refs=[{"page_no": 9, "block_no": 1}])


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    with tutor_env(monkeypatch) as state:
        yield state


def _tutor_prompt(env: dict[str, Any]) -> str:
    return str(env["transport"].calls[0].user_prompt)


def test_graph_claims_are_offered_and_cited_to_their_evidence(env: dict[str, Any]) -> None:
    env["graph"] = [CLAIM]
    env["transport"] = FakeTransport({"coverage": "full", "segments": [
        {"text": "PAP shows crazy paving.", "sources": ["S1"]},
        {"text": "Oedema can too.", "sources": ["K1"]}]},
        judge={"verdicts": [{"segment": n, "verdict": "supported", "reason": "Stated."}
                            for n in (1, 2)]})
    body = client.post("/v1/tutor/ask", json={"question": "Differentials for crazy paving?"}).json()
    assert body["graph_claims"] == 1 and body["excerpts_considered"] == 2
    assert body["intent"] == "ddx" and env["graph_call"][1:] == ([CHUNK], "ddx")
    cited = body["segments"][1]["citations"][0]
    assert (cited["chunk_id"], cited["page_from"]) == (str(CLAIM.chunk_id), 9)
    assert cited["block_refs"] == [{"page_no": 9, "block_no": 1}]
    prompt = _tutor_prompt(env)
    assert 'id="K1"' in prompt and '<intent name="ddx"' in prompt


def test_compare_searches_both_subjects_and_tells_the_model(env: dict[str, Any]) -> None:
    original = env["hits"]
    env["transport"] = FakeTransport({"coverage": "full", "segments": [
        {"text": "Dermoids contain fat.", "sources": ["S1"], "row": "Fat",
         "column": "Dermoid"}]})
    response = client.post("/v1/tutor/ask", json={"question": "Dermoid vs epidermoid?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "compare" and env["hits"] is original
    assert env["search"][1] == "epidermoid"  # the last search was the second subject
    assert '<intent name="compare" subjects="Dermoid; epidermoid"' in _tutor_prompt(env)
    assert (body["segments"][0]["row"], body["segments"][0]["column"]) == ("Fat", "Dermoid")
    thread = client.get(f"/v1/tutor/threads/{body['thread_id']}").json()
    assert thread["messages"][1]["intent"] == "compare"
    assert thread["messages"][1]["segments"][0]["row"] == "Fat"


def test_show_me_offers_more_figures(env: dict[str, Any]) -> None:
    env["figures"] = [{**FIGURE_HIT, "id": uuid4()} for _ in range(8)]
    body = client.post("/v1/tutor/ask", json={"question": "Show me crazy paving"}).json()
    assert body["intent"] == "show_me" and body["figures_considered"] == 6
    plain = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"}).json()
    assert plain["intent"] == "explain" and plain["figures_considered"] == 4


def test_quiz_hands_off_without_retrieval_or_model_calls(env: dict[str, Any]) -> None:
    response = client.post("/v1/tutor/ask", json={"question": "Quiz me on renal masses"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "quiz" and body["quiz_topic"] == "renal masses"
    assert body["segments"] == [] and body["grounding"] == "none"
    assert "Questions" in body["notice"]
    assert env["transport"].calls == [] and "search" not in env
    thread = client.get(f"/v1/tutor/threads/{body['thread_id']}").json()
    reply = thread["messages"][1]
    assert (reply["intent"], reply["quiz_topic"]) == ("quiz", "renal masses")
    assert reply["segments"] == []


def test_a_comparison_keeps_one_hit_per_subject() -> None:
    from apps.api.app.tutor.retrieval import cover_subjects

    main = [{"id": i} for i in range(4)]
    a, b = [{"id": 0}], [{"id": "b1"}, {"id": "b2"}]
    out = cover_subjects(main + [{"id": "b2"}], [a, b], 4)
    assert [h["id"] for h in out] == [0, 1, 2, "b2"]  # b's best-ranked hit replaces the tail
    assert cover_subjects(main, [[], a], 4) == main
