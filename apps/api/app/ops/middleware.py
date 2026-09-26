"""Per-request context: request id, trace ids, metrics, structured log, audit (ADR 0032).

Every request gets a UUID request id (a valid ``X-Request-ID`` is kept, anything
else replaced) that is echoed in the response, bound in the trace context for
model-call ledger rows and published Celery tasks, and written to audit rows.
The log line carries the route template (never the concrete path, which can
hold ids of private objects), status, duration, and tenant id once known.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from apps.api.app.observability import logger
from apps.api.app.ops import audit
from packages.observability import trace
from packages.observability.metrics import Counter, Histogram
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter("radbrain_http_requests_total", "HTTP requests by route and status.",
                   ("method", "route", "status"))
LATENCY = Histogram("radbrain_http_request_seconds", "HTTP request latency by route.",
                    ("method", "route"))


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", "unmatched"))


def _identity(request: Request) -> tuple[UUID | None, UUID | None]:
    tenant = getattr(request.state, "tenant_id", None)
    user = getattr(request.state, "user_id", None)
    return (tenant if isinstance(tenant, UUID) else None,
            user if isinstance(user, UUID) else None)


async def _audit(request: Request, route: str, status_code: int,
                 scope: audit.AuditScope) -> None:
    tenant_id, user_id = _identity(request)
    if tenant_id is None or user_id is None:
        return
    if not audit.should_audit(request.method, route, status_code):
        return
    params = {k: str(v) for k, v in request.path_params.items()}
    await audit.request_audit(audit.Mutation(tenant_id, user_id, request.method, route,
                                             status_code, params), scope)


async def request_context(request: Request, call_next: Any) -> Response:
    request_id = trace.coerce_request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    trace.set_request_id(request_id)
    trace.set_identity(None, None)
    scope = audit.open_scope()
    started = time.perf_counter()
    response: Response = await call_next(request)
    elapsed = time.perf_counter() - started
    response.headers["x-request-id"] = request_id
    route = route_template(request)
    await _audit(request, route, response.status_code, scope)
    REQUESTS.inc(request.method, route, str(response.status_code))
    LATENCY.observe(elapsed, request.method, route)
    tenant_id, _ = _identity(request)
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": route,
            "status_code": response.status_code,
            "duration_ms": int(elapsed * 1000),
            "tenant_id": str(tenant_id) if tenant_id else None,
        },
    )
    return response
