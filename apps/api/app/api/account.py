"""Account identity routes: current membership, tenant switch, admin ping.

The tenant name and kind come from the caller's membership row, read in the
caller's own tenant session (RLS), so a request can never describe a tenant it
does not belong to. ``resolve_memberships`` admits exactly one active
membership per subject, so a switch succeeds only for the caller's own tenant
and is refused (403) for any other, including tenants that do not exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Protocol
from uuid import UUID

from apps.api.app.schemas.common import TenantResponse
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1")

PrincipalDep = Annotated[Principal, Depends(principal_context)]

_MEMBERSHIP_SQL = text(
    """
    SELECT t.id, t.name, t.kind, m.role
    FROM memberships AS m
    JOIN tenants AS t ON t.id = m.tenant_id
    WHERE m.user_id = :user_id
      AND m.tenant_id = :tenant_id
      AND m.active
      AND m.deleted_at IS NULL
      AND t.deleted_at IS NULL
    """
)


class TenantDirectory(Protocol):
    async def membership(self, user_id: UUID, tenant_id: UUID) -> Mapping[str, Any] | None:
        """The caller's active membership in ``tenant_id`` with the tenant's name and kind."""


class SqlTenantDirectory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def membership(self, user_id: UUID, tenant_id: UUID) -> Mapping[str, Any] | None:
        result = await self._session.execute(
            _MEMBERSHIP_SQL, {"user_id": user_id, "tenant_id": tenant_id}
        )
        row = result.mappings().first()
        return dict(row) if row else None


def get_directory(
    session: Annotated[AsyncSession, Depends(tenant_db_session)],
) -> TenantDirectory:
    return SqlTenantDirectory(session)


DirectoryDep = Annotated[TenantDirectory, Depends(get_directory)]


async def _tenant_response(
    directory: TenantDirectory, principal: Principal, tenant_id: UUID
) -> TenantResponse:
    row = await directory.membership(principal.user_id, tenant_id)
    if row is None:
        raise HTTPException(status_code=403, detail="no active membership for this tenant")
    return TenantResponse(
        id=str(row["id"]), name=str(row["name"]), kind=str(row["kind"]), role=str(row["role"])
    )


@router.get("/me", response_model=TenantResponse, tags=["auth"])
async def me(principal: PrincipalDep, directory: DirectoryDep) -> TenantResponse:
    return await _tenant_response(directory, principal, principal.tenant_id)


@router.post("/tenants/switch", response_model=TenantResponse, tags=["auth"])
async def switch_tenant(
    tenant_id: UUID, principal: PrincipalDep, directory: DirectoryDep
) -> TenantResponse:
    # The session is bound to the caller's tenant; another tenant is never read.
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant switch denied")
    return await _tenant_response(directory, principal, tenant_id)


@router.get("/admin/ping", tags=["admin"])
async def admin_ping(principal: PrincipalDep) -> dict[str, str]:
    require_roles(principal, "org_admin", "superadmin")
    return {"status": "ok"}
