from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from apps.api.app.api.preview import preview_principal_context
from apps.api.app.preview.contracts import (
    PreviewClaimResponse,
    PreviewConceptResponse,
    PreviewConflictResponse,
    PreviewTutorRequest,
    PreviewTutorResponse,
)
from apps.api.app.preview.knowledge import ensure_knowledge, extract_source
from apps.api.app.preview.service import get_preview_state, require_preview
from apps.api.app.preview.tutor import ask
from apps.api.app.schemas.common import Citation
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(
    prefix="/v1/preview",
    tags=["preview: non-release"],
    dependencies=[Depends(require_preview)],
)


def _citation(value: dict[str, object]) -> Citation:
    return Citation.model_validate(value)


@router.get("/concepts", response_model=tuple[PreviewConceptResponse, ...])
def list_concepts(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> tuple[PreviewConceptResponse, ...]:
    state = get_preview_state()
    ensure_knowledge(state, principal.tenant_id, principal.user_id)
    return tuple(
        PreviewConceptResponse(
            id=str(item["id"]),
            name=str(item["name"]),
            type=str(item["type"]),
            status=str(item["status"]),
            claim_ids=tuple(str(value) for value in cast(tuple[object, ...], item["claim_ids"])),
        )
        for item in state.concepts_for(principal.tenant_id)
    )


@router.get("/claims", response_model=tuple[PreviewClaimResponse, ...])
def list_claims(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> tuple[PreviewClaimResponse, ...]:
    state = get_preview_state()
    ensure_knowledge(state, principal.tenant_id, principal.user_id)
    return tuple(
        PreviewClaimResponse(
            id=str(claim.id),
            text=claim.text,
            verification=claim.verification,
            citation=_citation(claim.citation),
        )
        for claim in state.claims(principal.tenant_id)
    )


@router.get("/conflicts", response_model=tuple[PreviewConflictResponse, ...])
def list_conflicts(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> tuple[PreviewConflictResponse, ...]:
    state = get_preview_state()
    ensure_knowledge(state, principal.tenant_id, principal.user_id)
    return tuple(
        PreviewConflictResponse(
            id=str(item["id"]),
            status=str(item["status"]),
            description=str(item["description"]),
            claim_ids=tuple(str(value) for value in cast(tuple[object, ...], item["claim_ids"])),
        )
        for item in state.conflicts_for(principal.tenant_id)
    )


@router.post("/sources/{source_id}/extract", response_model=tuple[PreviewClaimResponse, ...])
def extract(
    source_id: UUID,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> tuple[PreviewClaimResponse, ...]:
    try:
        claims = extract_source(
            get_preview_state(), principal.tenant_id, principal.user_id, source_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return tuple(
        PreviewClaimResponse(
            id=str(claim.id),
            text=claim.text,
            verification=claim.verification,
            citation=_citation(claim.citation),
        )
        for claim in claims
    )


@router.post("/tutor/ask", response_model=PreviewTutorResponse)
def ask_tutor(
    payload: PreviewTutorRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewTutorResponse:
    result = ask(get_preview_state(), principal.tenant_id, principal.user_id, payload.query)
    return PreviewTutorResponse(
        answer=str(result["answer"]),
        citations=tuple(
            _citation(value) for value in cast(tuple[dict[str, object], ...], result["citations"])
        ),
        figures=tuple(
            {
                "id": str(value["id"]),
                "page_no": value["page_no"],
                "caption": str(value["caption"]),
                "modality": str(value["modality"]),
                "image_key": str(value.get("image_key", "")),
            }
            for value in cast(tuple[dict[str, object], ...], result["figures"])
        ),
        grounding="mock_lexical_preview",
    )
