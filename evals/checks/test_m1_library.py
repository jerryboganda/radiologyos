"""M1 eval gate: ingestion, quarantine, provenance, and cited search.

Covers slices E, F, G, H of the A-Z queue:
  E  ingestion schema, private object-key policy, resumable visible job state
  F  parsing over synthetic multi-page / multi-section documents
  G  page/block/figure provenance
  H  cited search with tenant-scoped chunks and figures, plus the no-result
     and cross-tenant negatives

The three steps that need a provider or a later milestone stay visibly
`skipped` with a reason code rather than being faked as success. That is the
behaviour these tests pin down.

All content is synthetic. No private study material is read.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from apps.api.app.preview.library import (
    derive_object_key,
    ingest_source,
    search_chunks,
    search_figures,
)
from apps.worker.app.job_id import IngestStep
from evals.checks._harness import (
    ABDOMEN,
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

# The pipeline reports these as skipped because they are gated, not done.
EXPECTED_SKIPS = {
    IngestStep.EXTRACT_TABLES.value: "preview_not_implemented",
    IngestStep.EMBED_INDEX.value: "provider_gate_blocked",
    IngestStep.KNOWLEDGE_EXTRACTION.value: "milestone_m2_preview",
}


def test_ingest_reports_every_canonical_step_with_a_visible_status() -> None:
    state = new_state()
    _, job = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-steps")

    assert [s.name for s in job.steps.values()] == [step.value for step in IngestStep]
    assert job.status == "succeeded"
    # No step is left pending or running: every one is terminal.
    assert not [s for s in job.steps.values() if s.status in {"pending", "running"}]
    # Gated steps stay skipped and say why, rather than claiming success.
    for name, reason in EXPECTED_SKIPS.items():
        step = job.steps[name]
        assert step.status == "skipped", name
        assert step.error_code == reason


def test_ingest_is_idempotent_and_replays_the_same_job() -> None:
    state = new_state()
    first, first_job = ingest_source(
        state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-idem"
    )
    second, second_job = ingest_source(
        state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-idem"
    )

    assert first.id == second.id
    assert first_job.id == second_job.id
    assert len(state.jobs(TENANT_A)) == 1
    assert len(state.sources(TENANT_A)) == 1


def test_reusing_a_key_with_different_content_fails_closed() -> None:
    state = new_state()
    ingest_source(state, TENANT_A, OWNER_A, "A", "note", CHEST, "m1-conflict")
    with pytest.raises(ValueError, match="different content"):
        ingest_source(state, TENANT_A, OWNER_A, "B", "note", HEAD, "m1-conflict")


def test_idempotency_keys_do_not_collide_across_tenants() -> None:
    state = new_state()
    a, _ = ingest_source(state, TENANT_A, OWNER_A, "A", "note", CHEST, "shared-key")
    b, _ = ingest_source(state, TENANT_B, OWNER_B, "B", "note", HEAD, "shared-key")

    assert a.id != b.id
    assert state.idempotent_source(TENANT_A, "shared-key") == a.id
    assert state.idempotent_source(TENANT_B, "shared-key") == b.id


def test_empty_content_is_rejected_rather_than_stored_empty() -> None:
    state = new_state()
    with pytest.raises(ValueError, match="content is required"):
        ingest_source(state, TENANT_A, OWNER_A, "Empty", "note", "   \n ", "m1-empty")
    assert state.sources(TENANT_A) == []


@pytest.mark.parametrize(
    "body",
    [
        "Patient MRN: 12345678 presents with cough.",
        "medical record 99887766 filed",
    ],
)
def test_identifier_bearing_content_is_quarantined_not_indexed(body: str) -> None:
    """M1 privacy gate: identifiable content never becomes searchable."""
    state = new_state()
    source, job = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", body, "m1-mrn")

    assert source.status == "quarantined"
    # A quarantined source is never parsed, chunked, or searchable.
    assert source.chunk_count == 0
    assert source.page_count == 0
    assert state.source_chunks(TENANT_A, source.id) == []
    assert search_chunks(state, TENANT_A, "cough", limit=5) == []
    assert job.status == "failed"


def test_object_keys_are_tenant_prefixed_and_never_collide() -> None:
    key_a = derive_object_key(TENANT_A, UUID(int=1), "original/source.txt")
    key_b = derive_object_key(TENANT_B, UUID(int=1), "original/source.txt")

    assert key_a.startswith(f"tenants/{TENANT_A}/")
    assert key_b.startswith(f"tenants/{TENANT_B}/")
    assert key_a != key_b


def test_pages_split_on_form_feed_and_stay_addressable() -> None:
    state = new_state()
    source, _ = ingest_source(
        state, TENANT_A, OWNER_A, "Paged", "pdf", "Page one text.\fPage two text.", "m1-pages"
    )
    pages = [p for p in (state.page(TENANT_A, source.id, n) for n in range(1, 5)) if p]

    assert [p.page_no for p in pages] == [1, 2]
    assert source.page_count == 2
    for page in pages:
        assert page.tenant_id == TENANT_A
        assert page.source_id == source.id
        assert page.image_key.startswith(f"tenants/{TENANT_A}/")
        assert page.has_text_layer is True


def test_every_block_belongs_to_a_real_page_of_its_own_source() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-prov")
    pages = [p for p in (state.page(TENANT_A, source.id, n) for n in range(1, 8)) if p]
    assert pages

    seen = 0
    for page in pages:
        for block in state.page_blocks(TENANT_A, source.id, page.page_no):
            seen += 1
            assert block.tenant_id == TENANT_A
            assert block.source_id == source.id
            assert block.page_no == page.page_no
            assert block.text.strip()
    assert seen > 0


def test_every_chunk_cites_its_source_page_and_block_range() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-chunk")
    chunks = state.source_chunks(TENANT_A, source.id)

    assert chunks
    for chunk in chunks:
        assert chunk.tenant_id == TENANT_A
        assert chunk.source_id == source.id
        assert chunk.page_no >= 1
        assert chunk.text.strip()
        assert len(chunk.chunk_hash) == 64
        # The chunk's page and both block bounds must resolve inside this source.
        assert state.page(TENANT_A, source.id, chunk.page_no) is not None
        blocks = state.page_blocks(TENANT_A, source.id, chunk.page_no)
        ids = {b.id for b in blocks}
        assert chunk.block_start in ids
        assert chunk.block_end in ids


def test_search_returns_cited_tenant_scoped_hits_in_relevance_order() -> None:
    state = new_state()
    seed(state)
    hits = search_chunks(state, TENANT_A, "costophrenic angle", limit=5)

    assert hits, "expected a hit for a phrase present in the synthetic source"
    for chunk, score in hits:
        assert chunk.tenant_id == TENANT_A
        assert 0 < score <= 1
        assert "costophrenic" in chunk.text.lower()

    scores = [score for _, score in hits]
    assert scores == sorted(scores, reverse=True)
    # Relevance must be normalised, not raw overlap.
    assert max(scores) <= 1.0


def test_search_is_case_insensitive() -> None:
    state = new_state()
    ingest_source(state, TENANT_A, OWNER_A, "Abdomen", "note", ABDOMEN, "m1-case")

    lower = search_chunks(state, TENANT_A, "pneumoperitoneum", limit=5)
    upper = search_chunks(state, TENANT_A, "PNEUMOPERITONEUM", limit=5)

    assert lower and upper
    assert {c.id for c, _ in lower} == {c.id for c, _ in upper}


def test_search_respects_the_limit_and_returns_nothing_when_absent() -> None:
    state = new_state()
    seed(state)

    assert len(search_chunks(state, TENANT_A, "pleura mediastinum chest", limit=2)) <= 2
    assert search_chunks(state, TENANT_A, "quantum chromodynamics", limit=5) == []


def test_search_never_leaks_another_tenants_chunks() -> None:
    state = new_state()
    seed(state)  # tenant A gets the chest material
    ingest_source(state, TENANT_B, OWNER_B, "Head", "note", HEAD, "m1-x-b")

    # A phrase that exists only in tenant B's material.
    assert search_chunks(state, TENANT_A, "subarachnoid haemorrhage", limit=5) == []
    # A phrase that exists only in tenant A's material.
    assert search_chunks(state, TENANT_B, "costophrenic angle", limit=5) == []


def test_figure_markers_produce_tenant_prefixed_figures() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Figures", "note", FIGURES, "m1-fig-a")

    figures = state.source_figures(TENANT_A, source.id)
    assert len(figures) == 2
    for figure in figures:
        assert figure.tenant_id == TENANT_A
        assert figure.source_id == source.id
        assert figure.page_no >= 1
        assert figure.caption
        assert figure.modality in {"chest-xray", "axial-ct"}
        assert figure.image_key.startswith(f"tenants/{TENANT_A}/")
    # The figure must point at a real block on a real page.
    for figure in figures:
        ids = {b.id for b in state.page_blocks(TENANT_A, source.id, figure.page_no)}
        assert figure.block_id in ids


def test_figure_search_is_tenant_scoped_and_key_prefixed() -> None:
    state = new_state()
    source_a, _ = ingest_source(state, TENANT_A, OWNER_A, "Plate A", "note", FIGURES, "m1-fig-a")
    source_b, _ = ingest_source(state, TENANT_B, OWNER_B, "Plate B", "note", FIGURES, "m1-fig-b")

    a_figures = search_figures(state, TENANT_A, "chest radiograph", limit=6)
    assert a_figures, "expected the captioned chest figure to be findable"
    for figure in a_figures:
        assert figure.tenant_id == TENANT_A
        assert figure.source_id == source_a.id
        assert figure.image_key.startswith(f"tenants/{TENANT_A}/")

    b_figures = search_figures(state, TENANT_B, "chest radiograph", limit=6)
    assert b_figures
    for figure in b_figures:
        assert figure.tenant_id == TENANT_B
        assert figure.source_id == source_b.id
        assert figure.image_key.startswith(f"tenants/{TENANT_B}/")


def test_deleted_source_leaves_listings_and_search() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-del")
    assert search_chunks(state, TENANT_A, "costophrenic", limit=5)

    state.soft_delete_source(TENANT_A, source.id, state.now())

    assert state.sources(TENANT_A) == []
    assert search_chunks(state, TENANT_A, "costophrenic", limit=5) == []


def test_soft_delete_cannot_reach_another_tenant() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m1-del-x")

    assert state.soft_delete_source(TENANT_B, source.id, state.now()) is False
    assert [s.id for s in state.sources(TENANT_A)] == [source.id]


def test_chunking_stays_bounded_on_a_large_document() -> None:
    """Slice F readiness target: many sections must not become many oversized chunks."""
    state = new_state()
    body = "\n\n".join(
        f"## Section {i}\n\nSynthetic finding number {i} describes a pattern."
        for i in range(1, 201)
    )
    source, job = ingest_source(state, TENANT_A, OWNER_A, "Large", "note", body, "m1-large")
    chunks = state.source_chunks(TENANT_A, source.id)

    assert job.status == "succeeded"
    assert source.chunk_count == len(chunks)
    assert len(chunks) > 1, "a 200-section document should be chunked"
    # Chunks are word-bounded, so a large document stays a bounded number of them.
    assert all(len(c.text.split()) < 500 for c in chunks)
    # Block-derived ids are tenant-scoped, so two tenants never collide.
    other, _ = ingest_source(state, TENANT_B, OWNER_B, "Large", "note", body, "m1-large-b")
    assert {c.id for c in chunks}.isdisjoint(
        {c.id for c in state.source_chunks(TENANT_B, other.id)}
    )


@pytest.mark.parametrize("kind", ["note", "pdf", "docx", "unknown-kind"])
def test_ingestion_accepts_every_declared_source_kind(kind: str) -> None:
    state = new_state()
    source, job = ingest_source(
        state, TENANT_A, OWNER_A, f"Synthetic {kind}", kind, CHEST, f"m1-kind-{kind}"
    )
    assert job.status == "succeeded"
    assert source.kind == kind
