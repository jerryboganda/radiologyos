from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from apps.api.app.api.preview import preview_principal_context
from apps.api.app.preview.contracts import (
    PreviewAdminResponse,
    PreviewConflictResolutionRequest,
    PreviewConflictResponse,
    PreviewQueueResponse,
)
from apps.api.app.preview.knowledge import ensure_knowledge
from apps.api.app.preview.service import get_preview_state, require_preview
from apps.api.app.preview.state import PreviewAudit
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(
    prefix="/v1/preview",
    tags=["preview: non-release"],
    dependencies=[Depends(require_preview)],
)


@router.get("/editor/queues", response_model=PreviewQueueResponse)
def queues(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewQueueResponse:
    require_roles(principal, "editor", "org_admin", "superadmin")
    state = get_preview_state()
    ensure_knowledge(state, principal.tenant_id, principal.user_id)
    return PreviewQueueResponse(
        conflicts=tuple(
            PreviewConflictResponse(
                id=str(item["id"]),
                status=str(item["status"]),
                description=str(item["description"]),
                claim_ids=tuple(
                    str(value) for value in cast(tuple[object, ...], item["claim_ids"])
                ),
            )
            for item in state.conflicts_for(principal.tenant_id)
        ),
        pending_mappings=0,
        pending_questions=0,
    )


@router.post("/editor/conflicts/{conflict_id}/resolve", response_model=PreviewConflictResponse)
def resolve_conflict(
    conflict_id: UUID,
    payload: PreviewConflictResolutionRequest,
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewConflictResponse:
    require_roles(principal, "editor", "org_admin", "superadmin")
    state = get_preview_state()
    if not state.resolve_conflict(principal.tenant_id, conflict_id, payload.resolution):
        raise HTTPException(status_code=404, detail="conflict not found")
    state.add_audit(
        PreviewAudit(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="conflict.resolved",
            target_type="conflict",
            target_id=str(conflict_id),
            created_at=state.now(),
        )
    )
    conflict = next(
        item
        for item in state.conflicts_for(principal.tenant_id)
        if UUID(str(item["id"])) == conflict_id
    )
    return PreviewConflictResponse(
        id=str(conflict["id"]),
        status=str(conflict["status"]),
        description=str(conflict["description"]),
        claim_ids=tuple(str(value) for value in cast(tuple[object, ...], conflict["claim_ids"])),
    )


@router.get("/admin/overview", response_model=PreviewAdminResponse)
def admin_overview(
    principal: Annotated[Principal, Depends(preview_principal_context)],
) -> PreviewAdminResponse:
    require_roles(principal, "org_admin", "superadmin")
    state = get_preview_state()
    return PreviewAdminResponse(
        role=principal.role,
        source_count=len(state.sources(principal.tenant_id)),
        open_conflicts=len(state.conflicts_for(principal.tenant_id)),
        billing_status="preview_only",
    )
