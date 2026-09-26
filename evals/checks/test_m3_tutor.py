"""M3 eval gate: bounded retrieval, cited grounding, fail-closed refusals, thread isolation.

Drives the durable tutor over HTTP (``POST /v1/tutor/ask``: ``apps/api/app/api/
tutor.py``, ``apps/api/app/tutor``, ``packages/tutor``) with the real hybrid search
fusion, citation grounding, and judge wiring. Only the SQL leaves, thread storage
(``apps/api/tests/tutor_fakes.py``), and the model transport are fakes; the fake
tutor can only restate what it was shown and the fake judge accepts a sentence
only if its cited evidence contains it (``_m3_support``). It proves:

  M  retrieval is bounded to the declared top-k (8 excerpts, 4 figures), every
     grounded sentence carries a citation that resolves to a chunk retrieved for
     this question from the caller's own tenant, and the non-model path stays
     inside a generous latency budget;
  N  an unsupported question and an empty library refuse with no uncited text;
     unsupported, uncited, or forged-label sentences are dropped; an unavailable
     model gives 503/429/502 and a failed judge labels text "not verified";
  O  thread memory is bounded (rolling summary, verbatim window) and per owner,
     never crossing users or tenants; no tenant grounds on another's sources;
     degenerate questions are 422 or a refusal, never a confident uncited answer.

The row-level tenant proof for tutor threads runs as the runtime role in
``test_tutor_live.py`` / ``test_tutor_depth_live.py`` (CI). All content is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.main import app
from apps.api.app.tutor import retrieval
from apps.api.tests.tutor_fakes import tutor_env
from evals.checks._m3_support import (
    CHEST,
    HEAD,
    PRIVATE,
    USER_A,
    USER_A2,
    USER_B,
    USER_C,
    Corpus,
    EvidenceTransport,
    figure_hit,
)
from fastapi.testclient import TestClient
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.tutor.grounding import MAX_FIGURES, NOT_FOUND, NOT_FOUND_AFTER_WEB
from packages.tutor.memory import VERBATIM_MESSAGES

LATENCY_BUDGET_SECONDS = 2.0  # interactive path with instant fakes; catches unbounded work
client = TestClient(app)


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    with tutor_env(monkeypatch) as state:
        state["principal"] = USER_A
        corpus = Corpus(lambda: state["principal"])
        corpus.install(monkeypatch)
        corpus.add(USER_A, "Chest notes", CHEST)
        corpus.add(USER_A2, "Private notes", PRIVATE)
        corpus.add(USER_B, "Head notes", HEAD)
        state.update(corpus=corpus, transport=EvidenceTransport())
        yield state


def ask(env: dict[str, Any], question: str, **extra: Any) -> Any:
    return client.post("/v1/tutor/ask", json={"question": question, "allow_web": False,
                                              **extra})


def assert_grounded(env: dict[str, Any], body: dict[str, Any]) -> None:
    """Every sentence is cited to a chunk this caller may read, and says only what it says."""
    who, corpus = env["principal"], env["corpus"]
    assert body["segments"] and body["grounding"] == "sources"
    for segment in body["segments"]:
        assert segment["citations"], "an uncited sentence reached the answer"
        for citation in segment["citations"]:
            row = corpus.row(citation["chunk_id"])
            assert row is not None and row["tenant_id"] == who.tenant_id
            assert row["uploaded_by"] == who.user_id
            assert citation["source_id"] == str(row["source_id"])
            assert row["page_from"] <= citation["page_from"] <= row["page_to"]
            assert segment["text"].rstrip(".").lower() in row["text"].lower()


def refused(body: dict[str, Any], notice: str = NOT_FOUND) -> bool:
    return body["segments"] == [] and body["grounding"] == "none" and body["notice"] == notice


# ---------------------------------------------------------------- slice M


def test_every_grounded_sentence_carries_a_resolvable_citation(env: dict[str, Any]) -> None:
    response = ask(env, "What does costophrenic angle blunting mean?")
    assert response.status_code == 200, response.text
    body = response.json()
    assert_grounded(env, body)
    assert {s["support"] for s in body["segments"]} == {"supported"}
    assert body["judge"]["status"] == "ok" and body["judge"]["unsupported"] == 0
    assert env["corpus"].retrievals[-1][0] == USER_A.user_id


def test_retrieval_is_bounded_to_the_declared_top_k(env: dict[str, Any]) -> None:
    corpus = env["corpus"]
    for n in range(30):
        corpus.add(USER_A, f"Deck {n}", [f"Costophrenic angle blunting finding number {n}."])
    env["figures"] = [figure_hit(USER_A, f"Costophrenic angle blunting plate {n}.")
                      for n in range(10)]
    body = ask(env, "costophrenic angle blunting").json()
    assert body["excerpts_considered"] == retrieval.RETRIEVE == 8
    assert body["figures_considered"] == MAX_FIGURES == 4
    prompt = env["transport"].prompts[-1]
    assert prompt.count("<excerpt id=") == 8 and prompt.count("<figure id=") == 4
    cited = {c["chunk_id"] for s in body["segments"] for c in s["citations"]}
    assert 0 < len(cited) <= 8
    assert_grounded(env, body)


def test_the_non_model_path_stays_inside_the_latency_budget(env: dict[str, Any]) -> None:
    corpus = env["corpus"]
    for n in range(25):
        corpus.add(USER_A, f"Deck {n}", [f"Section {j}: costophrenic effusion synthetic "
                                         f"finding {j}." for j in range(20)])
    started = time.perf_counter()
    response = ask(env, "costophrenic effusion")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200 and response.json()["excerpts_considered"] == 8
    assert elapsed < LATENCY_BUDGET_SECONDS, f"took {elapsed:.3f}s"


# ---------------------------------------------------------------- slice N


@pytest.mark.parametrize(("allow_web", "notice"), [(False, NOT_FOUND),
                                                   (True, NOT_FOUND_AFTER_WEB)])
def test_a_question_with_no_support_refuses(
    env: dict[str, Any], allow_web: bool, notice: str
) -> None:
    body = ask(env, "quantum chromodynamics lagrangian", allow_web=allow_web).json()
    assert refused(body, notice)
    assert env["transport"].tutor_calls == []  # nothing retrieved: the tutor is never asked


def test_an_empty_library_refuses_rather_than_guessing(env: dict[str, Any]) -> None:
    env["principal"] = USER_C
    body = ask(env, "What does costophrenic angle blunting mean?").json()
    assert refused(body) and env["transport"].calls == []


def test_the_judge_drops_text_not_in_the_evidence(env: dict[str, Any]) -> None:
    env["transport"].extra = [
        {"text": "Costophrenic blunting always means malignancy.", "sources": ["S1"]}]
    body = ask(env, "What does costophrenic angle blunting mean?").json()
    assert all("malignancy" not in s["text"] for s in body["segments"])
    assert body["judge"]["unsupported"] == 1 and body["dropped_segments"] >= 1
    assert_grounded(env, body)


@pytest.mark.parametrize("sources", [[], ["S9"], ["F1"], ["00000000-0000-4000-8000-000000000000"]])
def test_uncited_or_forged_citations_never_survive(
    env: dict[str, Any], sources: list[str]
) -> None:
    transport = env["transport"]
    transport.compose = lambda prompt: {  # the model ignores its excerpts entirely
        "coverage": "full", "segments": [{"text": "Invented fact.", "sources": sources}]}
    body = ask(env, "costophrenic angle blunting").json()
    assert refused(body) and body["dropped_segments"] == 1


def test_figures_are_cited_by_retrieved_id_and_page(env: dict[str, Any]) -> None:
    figure = figure_hit(USER_A, "Frontal radiograph with a blunted left costophrenic angle.")
    env["figures"] = [figure]
    env["transport"].extra = [{"text": figure["description"], "sources": ["F1"]}]
    body = ask(env, "costophrenic angle radiograph").json()
    cited = [c for s in body["segments"] for c in s["citations"] if c["kind"] == "figure"]
    assert [(c["figure_id"], c["page_from"]) for c in cited] == [(str(figure["id"]), 5)]
    assert "image_key" not in cited[0]  # storage keys never leave the server


@pytest.mark.parametrize(("error", "status"), [(None, 503), (UsageLimitError("x"), 429),
                                               (ModelCallError("y"), 502)])
def test_an_unavailable_model_is_a_clear_state_not_fake_output(
    env: dict[str, Any], error: Exception | None, status: int
) -> None:
    if error is None:
        env["transport"] = None
    else:
        env["transport"].output = error
    response = ask(env, "What does costophrenic angle blunting mean?")
    assert response.status_code == status and "segments" not in response.json()
    assert env["repo"].threads == {} and "commit" not in env["session"].events


def test_a_failed_judge_labels_text_not_verified(env: dict[str, Any]) -> None:
    env["transport"].judge = ModelCallError("judge down")
    body = ask(env, "What does costophrenic angle blunting mean?").json()
    assert body["judge"]["status"] == "failed" and body["segments"]
    assert {s["support"] for s in body["segments"]} == {"not_verified"}


# ---------------------------------------------------------------- slice O


def _conversation_turns(prompt: str) -> int:
    if "<conversation" not in prompt:
        return 0
    block = prompt.split("<conversation", 1)[1].split("</conversation>", 1)[0]
    return sum(line.startswith(("user: ", "assistant: ")) for line in block.splitlines())


def test_thread_memory_is_bounded(env: dict[str, Any]) -> None:
    long = "Explain costophrenic angle blunting in detail please. " * 35
    thread = ask(env, long[:1990]).json()["thread_id"]
    for _ in range(11):
        assert ask(env, long[:1990], thread_id=thread).status_code == 200
    saved = env["repo"].memory[UUID(thread)]
    assert saved.covered > 0 and saved.summary
    last = env["transport"].prompts[-1]
    assert 0 < _conversation_turns(last) <= VERBATIM_MESSAGES
    assert "<thread_summary" in last and len(last) < 40_000


def test_thread_memory_is_per_owner_and_per_tenant(env: dict[str, Any]) -> None:
    secret = "What does costophrenic angle blunting mean for Ms Synthetic?"
    thread = ask(env, secret).json()["thread_id"]
    seen = len(env["transport"].prompts)
    for other in (USER_A2, USER_B):
        env["principal"] = other
        calls = len(env["transport"].calls)
        assert ask(env, "Continue", thread_id=thread).status_code == 404
        assert client.get(f"/v1/tutor/threads/{thread}").status_code == 404
        assert len(env["transport"].calls) == calls  # refused before any model call
        own = ask(env, "hyperdense basal cisterns or free gas under the diaphragm")
        assert own.status_code == 200 and own.json()["thread_id"] != thread
        assert all("Ms Synthetic" not in p for p in env["transport"].prompts[seen:])


def test_a_tenant_cannot_ground_on_another_tenants_or_users_sources(env: dict[str, Any]) -> None:
    assert refused(ask(env, "sulcal effacement subarachnoid").json())  # tenant B only
    assert refused(ask(env, "pneumoperitoneum rigler").json())  # A2's private upload
    env["principal"] = USER_B
    assert refused(ask(env, "costophrenic blunting effusion").json())  # tenant A only
    assert_grounded(env, ask(env, "sulcal effacement subarachnoid").json())
    env["principal"] = USER_A2
    assert_grounded(env, ask(env, "pneumoperitoneum rigler").json())
    assert {user for user, _ in env["corpus"].retrievals} == {
        USER_A.user_id, USER_B.user_id, USER_A2.user_id}


@pytest.mark.parametrize("question", ["", "a", "ab", "x" * 2001])
def test_degenerate_questions_are_rejected(env: dict[str, Any], question: str) -> None:
    assert ask(env, question).status_code == 422 and env["transport"].calls == []


@pytest.mark.parametrize("question", ["   ", "???", "\t\n\t", "?!" * 1000, ". . . . ."])
@pytest.mark.parametrize("allow_web", [False, True])
def test_degenerate_questions_never_get_a_confident_uncited_answer(
    env: dict[str, Any], question: str, allow_web: bool
) -> None:
    env["transport"].extra = [{"text": "A confident answer.", "sources": []}]
    response = ask(env, question, allow_web=allow_web)
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        body = response.json()
        assert all(s["citations"] for s in body["segments"])
        assert body["segments"] or body["notice"].startswith("Not found in your sources")
