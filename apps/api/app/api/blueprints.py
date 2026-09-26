"""Exam blueprints: packaged defaults, tenant overrides, and owner approval (ADR 0023)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from apps.api.app.assessment import blueprints
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/blueprints", tags=["assessment"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
BlueprintId = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,60}$")]
APPROVER_ROLES = ("org_admin", "superadmin")


class MixGroupOut(BaseModel):
    label: str
    systems: list[str]
    share: float


class NegativeMarkingOut(BaseModel):
    enabled: bool
    penalty: float


class BlueprintOut(BaseModel):
    id: str
    title: str
    exam_target: str
    curriculum_tag: str
    items: dict[str, int]
    duration_minutes: int
    mix_mode: str
    mix: list[MixGroupOut]
    negative_marking: NegativeMarkingOut
    pass_mark_percent: float | None
    unverified: list[str]
    sources: list[str]
    notes: str
    content_hash: str
    overrides: dict[str, Any]
    default: dict[str, Any]
    approved: bool
    approved_at: datetime | None


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overrides: dict[str, Any] = Field(
        description="Any of: items, duration_minutes, mix_mode, mix, negative_marking, "
                    "pass_mark_percent. An empty object restores the packaged default.")


class ApproveBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _missing(exc: blueprints.UnknownBlueprint) -> HTTPException:
    return HTTPException(status_code=404, detail="blueprint not found")


@router.get("", response_model=list[BlueprintOut])
async def list_blueprints(principal: PrincipalDep, session: SessionDep) -> list[BlueprintOut]:
    return [BlueprintOut(**b) for b in await blueprints.list_blueprints(session)]


@router.get("/{blueprint_id}", response_model=BlueprintOut)
async def get_blueprint(
    blueprint_id: BlueprintId, principal: PrincipalDep, session: SessionDep
) -> BlueprintOut:
    try:
        return BlueprintOut(**await blueprints.get_blueprint(session, blueprint_id))
    except blueprints.UnknownBlueprint as exc:
        raise _missing(exc) from exc


@router.put("/{blueprint_id}/overrides", response_model=BlueprintOut)
async def override_blueprint(
    blueprint_id: BlueprintId, body: OverrideRequest, principal: PrincipalDep,
    session: SessionDep,
) -> BlueprintOut:
    """Replace this tenant's override (owner/admin only); clears approval; audited."""
    require_roles(principal, *APPROVER_ROLES)
    try:
        view = await blueprints.set_overrides(session, principal, blueprint_id, body.overrides)
    except blueprints.UnknownBlueprint as exc:
        raise _missing(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BlueprintOut(**view)


@router.post("/{blueprint_id}/approve", response_model=BlueprintOut)
async def approve_blueprint(
    blueprint_id: BlueprintId, body: ApproveBlueprintRequest, principal: PrincipalDep,
    session: SessionDep,
) -> BlueprintOut:
    """Approve the effective blueprint with this hash (owner/admin only; audited)."""
    require_roles(principal, *APPROVER_ROLES)
    try:
        view = await blueprints.approve(session, principal, blueprint_id, body.content_hash)
    except blueprints.UnknownBlueprint as exc:
        raise _missing(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BlueprintOut(**view)
