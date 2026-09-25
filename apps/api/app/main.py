from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from apps.api.app.api.preview import router as preview_router
from apps.api.app.api.preview_admin import router as preview_admin_router
from apps.api.app.api.preview_assessment import router as preview_assessment_router
from apps.api.app.api.preview_knowledge import router as preview_knowledge_router
from apps.api.app.api.preview_learning import router as preview_learning_router
from apps.api.app.api.preview_operations import router as preview_operations_router
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import (
    get_system_session,
    tenant_context,
    tenant_session,
)
from apps.api.app.observability import logger
from apps.api.app.schemas.common import ErrorResponse, HealthResponse, TenantResponse
from apps.api.app.security.oidc import (
    OIDCVerificationError,
    OIDCVerifier,
    resolve_current_membership,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

app = FastAPI(
    title="radbrain API",
    version="0.1.0",
    description="Provenance-first, tenant-isolated radiology study platform.",
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)
oidc_verifier = OIDCVerifier(settings)
app.include_router(preview_router)
app.include_router(preview_knowledge_router)
app.include_router(preview_learning_router)
app.include_router(preview_assessment_router)
app.include_router(preview_operations_router)
app.include_router(preview_admin_router)


@app.middleware("http")
async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
    supplied_request_id = request.headers.get("x-request-id")
    try:
        request_id = str(UUID(supplied_request_id)) if supplied_request_id else str(uuid4())
    except ValueError:
        request_id = str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
        },
    )
    return response


@app.get("/health/live", response_model=HealthResponse, tags=["health"])
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok", service="api", environment=settings.app_env)


@app.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def readiness(
    session: Annotated[AsyncSession, Depends(get_system_session)],
) -> HealthResponse:
    try:
        import redis.asyncio as redis

        await session.execute(text("SELECT 1"))
        redis_client = cast(Any, redis).from_url(settings.redis_url, socket_connect_timeout=1)
        try:
            await redis_client.ping()
        finally:
            await redis_client.aclose()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dependency unavailable") from exc
    return HealthResponse(status="ready", service="api", environment=settings.app_env)


def _local_principal(
    x_user_id: str | None,
    x_tenant_id: str | None,
    x_role: str | None,
) -> Principal | None:
    if not x_user_id or not x_tenant_id:
        return None
    try:
        user_id = UUID(x_user_id)
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid local identity") from exc
    allowed_roles = {"student", "editor", "org_admin", "superadmin"}
    role = x_role or "student"
    if role not in allowed_roles:
        raise HTTPException(status_code=400, detail="invalid local role")
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


async def principal_from_request(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    request: Request,
    session: Annotated[AsyncSession, Depends(get_system_session)],
    x_user_id: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Principal:
    """Authenticate OIDC access and resolve current membership from the database."""
    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="bearer token required")
        try:
            identity = oidc_verifier.verify(credentials.credentials)
            principal = await resolve_current_membership(session, identity.subject)
        except OIDCVerificationError as exc:
            raise HTTPException(status_code=401, detail="invalid access token") from exc
        request.state.tenant_id = principal.tenant_id
        request.state.requires_tenant_session = True
        return principal

    if not settings.is_local_development:
        raise HTTPException(status_code=401, detail="OIDC token required")

    local_principal = _local_principal(x_user_id, x_tenant_id, x_role)
    if local_principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    request.state.tenant_id = local_principal.tenant_id
    request.state.local_tenant_id = local_principal.tenant_id
    request.state.requires_tenant_session = False
    return local_principal


async def principal_context(
    request: Request,
    principal: Annotated[Principal, Depends(principal_from_request)],
) -> AsyncIterator[Principal]:
    if getattr(request.state, "requires_tenant_session", False):
        async with tenant_session(principal.tenant_id) as session:
            request.state.tenant_session = session
            try:
                yield principal
            finally:
                del request.state.tenant_session
    else:
        with tenant_context(principal.tenant_id):
            yield principal


async def tenant_db_session(
    request: Request,
    principal: Annotated[Principal, Depends(principal_context)],
) -> AsyncIterator[AsyncSession]:
    """Yield a transaction-local session for OIDC or explicitly local identity."""
    session = getattr(request.state, "tenant_session", None)
    if isinstance(session, AsyncSession):
        yield session
        return
    local_tenant_id = getattr(request.state, "local_tenant_id", None)
    if isinstance(local_tenant_id, UUID) and local_tenant_id == principal.tenant_id:
        async with tenant_session(principal.tenant_id) as local_session:
            yield local_session
        return
    raise HTTPException(status_code=500, detail="tenant session unavailable")


@app.get(f"{settings.api_prefix}/me", response_model=TenantResponse, tags=["auth"])
async def me(principal: Annotated[Principal, Depends(principal_context)]) -> TenantResponse:
    return TenantResponse(
        id=str(principal.tenant_id),
        name="Authenticated tenant",
        kind="solo",
        role=principal.role,
    )


@app.post(f"{settings.api_prefix}/tenants/switch", response_model=TenantResponse, tags=["auth"])
async def switch_tenant(
    tenant_id: UUID,
    principal: Annotated[Principal, Depends(principal_context)],
) -> TenantResponse:
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant switch denied")
    return TenantResponse(
        id=str(tenant_id),
        name="Authenticated tenant",
        kind="solo",
        role=principal.role,
    )


@app.post(
    f"{settings.api_prefix}/me/export",
    response_model=ErrorResponse,
    status_code=501,
    tags=["data-rights"],
)
async def export_data(
    principal: Annotated[Principal, Depends(principal_context)],
) -> ErrorResponse:
    raise HTTPException(status_code=501, detail="data export is not available in preview mode")


@app.delete(
    f"{settings.api_prefix}/me",
    response_model=ErrorResponse,
    status_code=501,
    tags=["data-rights"],
)
async def delete_account(
    principal: Annotated[Principal, Depends(principal_context)],
) -> ErrorResponse:
    raise HTTPException(status_code=501, detail="account deletion is not available in preview mode")


@app.get(f"{settings.api_prefix}/admin/ping", tags=["admin"])
async def admin_ping(
    principal: Annotated[Principal, Depends(principal_context)],
) -> dict[str, str]:
    require_roles(principal, "org_admin", "superadmin")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.api.app.main:app", host="127.0.0.1", port=8000, reload=settings.debug)
