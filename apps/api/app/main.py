from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from apps.api.app.api.account import router as account_router
from apps.api.app.api.admin_usage import router as admin_usage_router
from apps.api.app.api.assessment import router as assessment_router
from apps.api.app.api.billing import router as billing_router
from apps.api.app.api.blueprints import router as blueprints_router
from apps.api.app.api.curriculum import router as curriculum_router
from apps.api.app.api.data_rights import router as data_rights_router
from apps.api.app.api.disputes import router as disputes_router
from apps.api.app.api.exams import router as exams_router
from apps.api.app.api.knowledge import router as knowledge_router
from apps.api.app.api.library import router as library_router
from apps.api.app.api.notifications import router as notifications_router
from apps.api.app.api.question_review import router as question_review_router
from apps.api.app.api.study import router as study_router
from apps.api.app.api.study_cards import router as study_cards_router
from apps.api.app.api.study_sessions import router as study_sessions_router
from apps.api.app.api.tutor import router as tutor_router
from apps.api.app.api.tutor_images import router as tutor_images_router
from apps.api.app.api.viva import router as viva_router
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import (
    get_system_session,
)
from apps.api.app.observability import logger
from apps.api.app.schemas.common import ErrorResponse, HealthResponse
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
    local_principal,
)
from apps.api.app.security.oidc import (
    OIDCVerifier,
)
from apps.api.app.security.principal import Principal
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer
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
app.include_router(library_router)
app.include_router(admin_usage_router)
app.include_router(notifications_router)
app.include_router(tutor_router)
app.include_router(tutor_images_router)
app.include_router(question_review_router)
app.include_router(assessment_router)
app.include_router(exams_router)
app.include_router(viva_router)
app.include_router(study_router)
app.include_router(study_sessions_router)
app.include_router(knowledge_router)
app.include_router(data_rights_router)
app.include_router(billing_router)
app.include_router(blueprints_router)
app.include_router(curriculum_router)
app.include_router(disputes_router)
app.include_router(study_cards_router)
# Identity routes last, where /v1/me and /v1/tenants/switch always sat in the contract.
app.include_router(account_router)


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
    """Retained as a thin alias so existing importers keep working."""
    return local_principal(x_user_id, x_tenant_id, x_role)


# Principal resolution lives in apps.api.app.security.context so that every
# router shares one implementation and the production/local identity rule cannot
# drift between routes. These names remain here as the app's bound instances.
principal_from_request, principal_context = build_shared_dependencies()

# Session handling is defined beside the principal dependencies, so a request can
# never have a tenant session opened by one module and closed by another.
tenant_db_session = build_tenant_db_session_dependency(principal_context)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.api.app.main:app", host="127.0.0.1", port=8000, reload=settings.debug)
