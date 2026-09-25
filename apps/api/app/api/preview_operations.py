from __future__ import annotations

from typing import Annotated

from apps.api.app.api.preview import preview_principal_context
from apps.api.app.preview.contracts import (
    PreviewBillingResponse,
    PreviewCapabilitiesResponse,
    PreviewLocalModeResponse,
    PreviewMarkdownResponse,
    PreviewReleaseAuditResponse,
)
from apps.api.app.preview.operations import (
    billing_status,
    capabilities,
    local_mode_status,
    markdown_export,
    release_audit,
)
from apps.api.app.preview.service import get_preview_state, require_preview
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends

router = APIRouter(
    prefix="/v1/preview",
    tags=["preview: non-release"],
    dependencies=[Depends(require_preview)],
)


@router.get("/billing/status", response_model=PreviewBillingResponse)
def billing(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewBillingResponse:
    return PreviewBillingResponse.model_validate(
        billing_status(get_preview_state(), principal.tenant_id)
    )


@router.get("/export/markdown", response_model=PreviewMarkdownResponse)
def export_markdown(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewMarkdownResponse:
    return PreviewMarkdownResponse(
        filename="radbrain-preview.md",
        markdown=markdown_export(get_preview_state(), principal.tenant_id, principal.user_id),
    )


@router.get("/capabilities", response_model=PreviewCapabilitiesResponse)
def capability_matrix(
    _principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewCapabilitiesResponse:
    return PreviewCapabilitiesResponse(capabilities=tuple(capabilities()))


@router.get("/local-mode", response_model=PreviewLocalModeResponse)
def local_mode(
    _principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewLocalModeResponse:
    return PreviewLocalModeResponse.model_validate(local_mode_status())


@router.get("/release-audit", response_model=PreviewReleaseAuditResponse)
def audit(
    _principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewReleaseAuditResponse:
    return PreviewReleaseAuditResponse.model_validate(release_audit())
