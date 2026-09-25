from __future__ import annotations

from uuid import UUID

from apps.api.app.preview.library import ingest_source
from apps.api.app.preview.state import PreviewClaim, PreviewState

_SYNTHETIC_TEXT = (
    "# Synthetic thoracic imaging\n\n"
    "A synthetic finding describes a ground-glass opacity.\n\n"
    "A synthetic management note recommends a follow-up comparison.\n"
)


def ensure_knowledge(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> None:
    tenant = state.tenant(tenant_id)
    if tenant.claims or tenant.concepts:
        return
    source, _job = ingest_source(
        state,
        tenant_id,
        owner_id,
        "Synthetic knowledge fixture",
        "note",
        _SYNTHETIC_TEXT,
        "knowledge-fixture-v1",
    )
    chunks = state.source_chunks(tenant_id, source.id)
    if not chunks:
        return
    citation = {
        "source_id": str(source.id),
        "page_no": chunks[0].page_no,
        "block_id": str(chunks[0].block_start),
        "bbox": [0.0, 0.0, 0.0, 0.0],
    }
    claim_id = state.new_id()
    state.add_claim(
        PreviewClaim(
            id=claim_id,
            tenant_id=tenant_id,
            source_id=source.id,
            text="A synthetic finding describes a ground-glass opacity.",
            citation=citation,
            verification="verified",
        )
    )
    state.add_concept(
        {
            "id": str(state.new_id()),
            "tenant_id": str(tenant_id),
            "name": "Ground-glass opacity",
            "type": "finding",
            "status": "verified",
            "claim_ids": [str(claim_id)],
        }
    )
    state.add_conflict(
        {
            "id": str(state.new_id()),
            "tenant_id": str(tenant_id),
            "status": "open",
            "description": "Synthetic sources disagree about follow-up timing.",
            "claim_ids": [str(claim_id)],
        }
    )


def extract_source(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    source_id: UUID,
) -> list[PreviewClaim]:
    source = state.source(tenant_id, source_id)
    if source is None or source.owner_id != owner_id or source.status != "ready":
        raise LookupError("source not found")
    existing = {claim.source_id for claim in state.claims(tenant_id)}
    if source_id in existing:
        return [claim for claim in state.claims(tenant_id) if claim.source_id == source_id]
    chunks = state.source_chunks(tenant_id, source_id)
    created: list[PreviewClaim] = []
    for chunk in chunks:
        claim = PreviewClaim(
            id=state.new_id(),
            tenant_id=tenant_id,
            source_id=source_id,
            text=chunk.text.splitlines()[0],
            citation={
                "source_id": str(source_id),
                "page_no": chunk.page_no,
                "block_id": str(chunk.block_start),
                "bbox": [0.0, 0.0, 0.0, 0.0],
            },
        )
        state.add_claim(claim)
        created.append(claim)
    return created


def concepts(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> list[dict[str, object]]:
    ensure_knowledge(state, tenant_id, owner_id)
    return state.concepts_for(tenant_id)


def claims(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> list[PreviewClaim]:
    ensure_knowledge(state, tenant_id, owner_id)
    return state.claims(tenant_id)


def conflicts(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> list[dict[str, object]]:
    ensure_knowledge(state, tenant_id, owner_id)
    return state.conflicts_for(tenant_id)
