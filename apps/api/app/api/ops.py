"""Readiness detail and the internal ``/metrics`` endpoint (ADR 0032).

``/health/ready`` checks PostgreSQL, Redis, and object storage and names each
as ``ok`` or ``unavailable`` (no error text, host, or credential). ``/metrics``
serves Prometheus text to internal callers only: a request carrying any
forwarding header is refused, the client address must be loopback or private,
and when ``METRICS_TOKEN`` is set a matching bearer token is also required.
Refusals answer 404 so the endpoint is not discoverable from outside.
"""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Mapping
from typing import Annotated, Any, Literal, cast

from apps.api.app.core.config import Settings, get_settings
from apps.api.app.db.session import get_system_session
from apps.api.app.ops import middleware, ratelimit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse
from packages.observability import metrics
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["health"])
Check = Literal["ok", "unavailable"]
FORWARDING_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-host")
SHARED = {
    "radbrain_job_steps_total": "Worker job step outcomes.",
    "radbrain_model_calls_total": "Model call attempts by agent, backend, and outcome.",
    "radbrain_model_call_seconds_total": "Seconds spent in model calls.",
}


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "unavailable"]
    service: str
    environment: str
    checks: dict[str, Check]


async def _database(session: AsyncSession) -> Check:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return "unavailable"
    return "ok"


async def _redis(settings: Settings) -> Check:
    try:
        import redis.asyncio as redis

        client = cast(Any, redis).from_url(settings.redis_url, socket_connect_timeout=1)
        try:
            await client.ping()
        finally:
            await client.aclose()
    except Exception:
        return "unavailable"
    return "ok"


def _object_storage(settings: Settings) -> Check:
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4", connect_timeout=2, read_timeout=2,
                          retries={"max_attempts": 1}, s3={"addressing_style": "path"}),
        )
        client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        return "unavailable"
    return "ok"


@router.get("/health/ready", response_model=ReadinessResponse,
            responses={503: {"model": ReadinessResponse}})
async def readiness(
    session: Annotated[AsyncSession, Depends(get_system_session)],
) -> JSONResponse:
    settings = get_settings()
    checks: dict[str, Check] = {
        "database": await _database(session),
        "redis": await _redis(settings),
        "object_storage": await run_in_threadpool(_object_storage, settings),
    }
    ready = all(value == "ok" for value in checks.values())
    body = ReadinessResponse(status="ready" if ready else "unavailable", service="api",
                             environment=settings.app_env, checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)


def metrics_allowed(client_host: str | None, headers: Mapping[str, str], token: str) -> bool:
    """Internal network only; plus a bearer token when one is configured."""
    if any(name in headers for name in FORWARDING_HEADERS):
        return False
    if token:
        supplied = headers.get("authorization", "")
        return hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode())
    try:
        address = ipaddress.ip_address(client_host or "")
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def render_metrics() -> str:
    lines: list[str] = []
    for metric in (middleware.REQUESTS, middleware.LATENCY, ratelimit.RATE_LIMITED):
        lines.extend(metric.render())
    shared = metrics.shared()
    for name, help_text in SHARED.items():
        lines.extend(metrics.render_shared(name, help_text, shared.read(name)))
    return "\n".join(lines) + "\n"


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics_endpoint(request: Request) -> PlainTextResponse:
    host = request.client.host if request.client else None
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not metrics_allowed(host, headers, get_settings().metrics_token):
        raise HTTPException(status_code=404, detail="Not Found")
    body = await run_in_threadpool(render_metrics)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")
