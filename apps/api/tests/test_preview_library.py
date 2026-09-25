from __future__ import annotations

from uuid import UUID

from apps.api.app.preview.library import ingest_source, search_chunks, search_figures
from apps.api.app.preview.state import PreviewState

TENANT_A = UUID("20000000-0000-0000-0000-000000000002")
TENANT_B = UUID("30000000-0000-0000-0000-000000000003")
USER_A = UUID("10000000-0000-0000-0000-000000000001")
USER_B = UUID("10000000-0000-0000-0000-000000000009")
SOURCE_TEXT = (
    "# Chest\n\nSynthetic finding.\n\n[[figure:CT]]\n"
    "A synthetic figure caption.\n\f# Cardiac\n\nSynthetic cardiac finding."
)


def test_preview_ingestion_creates_provenance_and_idempotent_job() -> None:
    state = PreviewState()

    source, job = ingest_source(
        state, TENANT_A, USER_A, "Synthetic notes", "note", SOURCE_TEXT, "key-1"
    )
    repeated, repeated_job = ingest_source(
        state, TENANT_A, USER_A, "Synthetic notes", "note", SOURCE_TEXT, "key-1"
    )

    assert repeated.id == source.id
    assert repeated_job.id == job.id
    assert source.status == "ready"
    assert source.page_count == 2
    assert source.figure_count == 1
    assert source.chunk_count >= 1
    assert source.object_key.startswith(f"tenants/{TENANT_A}/sources/{source.id}/")
    assert job.status == "succeeded"
    assert job.steps["extract_tables"].status == "skipped"
    assert job.steps["embed_index"].error_code == "provider_gate_blocked"
    assert search_chunks(state, TENANT_A, "synthetic finding")
    assert search_figures(state, TENANT_A, "CT")


def test_preview_idempotency_rejects_conflicting_content() -> None:
    state = PreviewState()
    ingest_source(state, TENANT_A, USER_A, "First", "note", SOURCE_TEXT, "same-key")

    try:
        ingest_source(state, TENANT_A, USER_A, "Second", "note", "Different", "same-key")
    except ValueError as exc:
        assert "reused" in str(exc)
    else:
        raise AssertionError("conflicting idempotency content was accepted")


def test_preview_ingestion_quarantines_identifier_content() -> None:
    state = PreviewState()

    source, job = ingest_source(
        state, TENANT_A, USER_A, "Quarantine", "note", "MRN: ABC-12345", "key-2"
    )

    assert source.status == "quarantined"
    assert source.page_count == 0
    assert job.status == "failed"


def test_preview_search_never_crosses_tenants() -> None:
    state = PreviewState()
    ingest_source(state, TENANT_A, USER_A, "Tenant A", "note", SOURCE_TEXT, "a")
    ingest_source(state, TENANT_B, USER_B, "Tenant B", "note", "Different synthetic content.", "b")

    assert not search_chunks(state, TENANT_B, "chest")
    assert not search_chunks(state, TENANT_B, "cardiac finding")
