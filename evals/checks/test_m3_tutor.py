"""M3 eval gate: retrieval stages, grounding, and cache/thread isolation.

Covers slices M, N, O of the A-Z queue:
  M  explicit retrieval stages, fusion, and a latency target
  N  grounding, citations, figure cards, and the ungrounded-output guard
  O  tutor thread memory, the "not in your sources" answer, and tenant-aware
     cache boundaries

All content is synthetic.
"""

from __future__ import annotations

import time
from uuid import UUID

import pytest
from apps.api.app.preview.library import ingest_source
from apps.api.app.preview.state import PreviewState
from apps.api.app.preview.tutor import ask
from evals.checks._harness import (
    CHEST,
    FIGURES,
    HEAD,
    OWNER_A,
    OWNER_B,
    TENANT_A,
    TENANT_B,
    new_state,
    seed,
)

# Slice M target: a grounded preview answer is an interactive operation, so a
# generous ceiling still catches accidental full scans or unbounded work.
LATENCY_BUDGET_SECONDS = 2.0

UNGROUNDED = "I do not have a grounded answer in the selected sources."


def grounded_state() -> PreviewState:
    state = new_state()
    ingest_source(state, TENANT_A, OWNER_A, "Plate", "note", FIGURES, "m3-fig")
    seed(state)
    return state


# ---------------------------------------------------------------- slice M


def test_every_grounded_sentence_carries_a_citation_marker() -> None:
    state = grounded_state()
    answer = ask(state, TENANT_A, OWNER_A, "costophrenic angle")

    assert answer["answer"] != UNGROUNDED
    sentences = [s for s in answer["answer"].split(". ") if s.strip()]
    assert sentences
    assert all("[1]" in s for s in sentences)


def test_a_grounded_answer_cites_only_real_tenant_scoped_locations() -> None:
    state = grounded_state()
    result = ask(state, TENANT_A, OWNER_A, "hilar lymphadenopathy")

    citations = result["citations"]
    assert citations, "a grounded answer must carry at least one citation"
    for citation in citations:
        assert UUID(citation["source_id"]).version == 4
        assert int(citation["page_no"]) >= 1
        assert citation["block_id"]
        source = state.source(TENANT_A, UUID(citation["source_id"]))
        assert source is not None
        assert source.tenant_id == TENANT_A
        assert state.page(TENANT_A, source.id, int(citation["page_no"])) is not None


def test_retrieval_is_bounded_to_the_declared_top_k() -> None:
    state = new_state()
    for i in range(12):
        ingest_source(
            state,
            TENANT_A,
            OWNER_A,
            f"Doc {i}",
            "note",
            f"## Note {i}\n\ncostophrenic angle effusion finding {i}.",
            f"m3-fan-{i}",
        )
    result = ask(state, TENANT_A, OWNER_A, "costophrenic angle")

    assert len(result["citations"]) <= 4
    assert result["figures"] is not None


def test_preview_answer_latency_stays_inside_the_budget() -> None:
    state = new_state()
    for i in range(25):
        ingest_source(
            state,
            TENANT_A,
            OWNER_A,
            f"Doc {i}",
            "note",
            "\n\n".join(
                f"## Section {j}\n\ncostophrenic effusion synthetic finding {j}." for j in range(20)
            ),
            f"m3-lat-{i}",
        )

    started = time.perf_counter()
    ask(state, TENANT_A, OWNER_A, "costophrenic effusion")
    elapsed = time.perf_counter() - started

    assert elapsed < LATENCY_BUDGET_SECONDS, f"took {elapsed:.3f}s"


def test_grounding_mode_is_declared_and_not_a_provider_claim() -> None:
    result = ask(grounded_state(), TENANT_A, OWNER_A, "costophrenic angle")
    assert result["grounding"] == "mock_lexical_preview"
    assert result["mode"] == "preview"


# ---------------------------------------------------------------- slice N


def test_a_question_with_no_support_fails_closed_with_no_citations() -> None:
    result = ask(grounded_state(), TENANT_A, OWNER_A, "quantum chromodynamics")

    assert result["answer"] == UNGROUNDED
    assert result["citations"] == []


def test_an_empty_tenant_refuses_rather_than_guessing() -> None:
    state = new_state()
    result = ask(state, TENANT_A, OWNER_A, "anything at all")

    assert result["answer"] == UNGROUNDED
    assert result["citations"] == []


def test_figures_are_returned_with_captions_and_tenant_prefixed_keys() -> None:
    state = grounded_state()
    result = ask(state, TENANT_A, OWNER_A, "chest radiograph opacity")

    figures = result["figures"]
    assert figures, "expected the captioned figure to be attached"
    for figure in figures:
        assert figure["caption"]
        assert figure["modality"]
        assert figure["image_key"].startswith(f"tenants/{TENANT_A}/")


def test_no_answer_text_is_invented_beyond_the_retrieved_evidence() -> None:
    """Slice N: the answer must be assembled only from cited chunk text."""
    state = grounded_state()
    result = ask(state, TENANT_A, OWNER_A, "hilar lymphadenopathy")
    retrieved = " ".join(
        state.source_chunks(TENANT_A, UUID(c["source_id"])).__iter__().__next__().text
        for c in result["citations"][:1]
    )
    for sentence in result["answer"].split("[1]"):
        fragment = sentence.strip().rstrip(".").strip()
        if len(fragment.split()) > 3:
            assert fragment in retrieved


# ---------------------------------------------------------------- slice O


def test_thread_memory_records_the_exchange_for_the_same_owner() -> None:
    state = grounded_state()
    ask(state, TENANT_A, OWNER_A, "costophrenic angle")
    ask(state, TENANT_A, OWNER_A, "hilar lymphadenopathy")

    thread = state.thread(TENANT_A, OWNER_A)
    assert [m["role"] for m in thread] == ["user", "assistant", "user", "assistant"]
    assert thread[0]["content"] == "costophrenic angle"
    assert thread[-1]["citations"]


def test_thread_memory_is_bounded() -> None:
    state = grounded_state()
    for i in range(40):
        ask(state, TENANT_A, OWNER_A, f"costophrenic angle query {i}")

    assert len(state.thread(TENANT_A, OWNER_A)) <= 40


def test_thread_memory_is_per_owner() -> None:
    state = grounded_state()
    ask(state, TENANT_A, OWNER_A, "costophrenic angle")
    ask(state, TENANT_A, OWNER_B, "hilar lymphadenopathy")

    a_thread = state.thread(TENANT_A, OWNER_A)
    b_thread = state.thread(TENANT_A, OWNER_B)
    assert [m["content"] for m in a_thread if m["role"] == "user"] == ["costophrenic angle"]
    assert [m["content"] for m in b_thread if m["role"] == "user"] == ["hilar lymphadenopathy"]


def test_thread_memory_never_crosses_tenants() -> None:
    state = grounded_state()
    seed(state, TENANT_B, OWNER_B)
    ingest_source(state, TENANT_B, OWNER_B, "Head", "note", HEAD, "m3-b")

    ask(state, TENANT_A, OWNER_A, "costophrenic angle")
    ask(state, TENANT_B, OWNER_B, "subarachnoid haemorrhage")

    a_thread = state.thread(TENANT_A, OWNER_A)
    b_thread = state.thread(TENANT_B, OWNER_B)
    assert not any("subarachnoid" in str(m.get("content")) for m in a_thread)
    assert not any("costophrenic" in str(m.get("content")) for m in b_thread)


def test_a_tenant_cannot_ground_on_another_tenants_sources() -> None:
    # Build a clean two-tenant world where each phrase is unique to one tenant.
    state = new_state()
    ingest_source(state, TENANT_A, OWNER_A, "Chest", "note", CHEST, "m3-iso-a")
    ingest_source(state, TENANT_B, OWNER_B, "Head", "note", HEAD, "m3-iso-b")

    # "sulcal effacement" exists only in tenant B's head material.
    assert "sulcal effacement" in HEAD
    assert "sulcal effacement" not in CHEST
    from_a = ask(state, TENANT_A, OWNER_A, "sulcal effacement")
    assert from_a["answer"] == UNGROUNDED
    assert from_a["citations"] == []

    # "costophrenic" exists only in tenant A's chest material.
    assert "costophrenic" in CHEST
    assert "costophrenic" not in HEAD
    from_b = ask(state, TENANT_B, OWNER_B, "costophrenic")
    assert from_b["answer"] == UNGROUNDED
    assert from_b["citations"] == []

    # Each tenant still answers from its own material.
    assert ask(state, TENANT_A, OWNER_A, "costophrenic")["citations"]
    assert ask(state, TENANT_B, OWNER_B, "sulcal effacement")["citations"]


def test_grounded_state_helper_is_reused_consistently() -> None:
    """Guards the fixture itself so a broken fixture cannot mask a real failure."""
    state = grounded_state()
    assert state.sources(TENANT_A)
    assert not state.sources(TENANT_B)


@pytest.mark.parametrize("query", ["", "   ", "a", "???"])
def test_degenerate_queries_never_produce_a_confident_uncited_answer(query: str) -> None:
    result = ask(grounded_state(), TENANT_A, OWNER_A, query)
    if result["answer"] != UNGROUNDED:
        assert result["citations"], "a non-refusal answer must be cited"
