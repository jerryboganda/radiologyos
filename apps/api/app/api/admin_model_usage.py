"""Admin view of the model-call ledger (``llm_calls``, ADR 0032).

Per day, agent, and backend: attempts by outcome, tokens, the transport-reported
cost (for subscription calls an API-price equivalent, not a bill), and mean
duration; plus usage-limit errors in the last hour and the tenant's
``model_usage_limit`` alerts. Counts and names only — the ledger holds no text.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/admin", tags=["admin"])
PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
ADMIN_ROLES = ("org_admin", "superadmin")
ROWS = text(
    """
    SELECT (created_at AT TIME ZONE 'UTC')::date AS day, agent, backend,
           count(*) AS calls,
           count(*) FILTER (WHERE status = 'ok') AS ok,
           count(*) FILTER (WHERE status = 'error') AS errors,
           count(*) FILTER (WHERE status = 'usage_limit') AS usage_limit,
           count(*) FILTER (WHERE status = 'rejected') AS rejected,
           coalesce(sum(input_tokens), 0) AS input_tokens,
           coalesce(sum(output_tokens), 0) AS output_tokens,
           coalesce(sum(cost_usd), 0)::float8 AS cost_usd,
           coalesce(avg(duration_ms), 0)::int AS avg_duration_ms
    FROM llm_calls
    WHERE created_at >= now() - make_interval(days => :days)
    GROUP BY 1, 2, 3
    ORDER BY 1 DESC, 2, 3
    """
)


class UsageRow(BaseModel):
    day: date
    agent: str
    backend: str
    calls: int
    ok: int
    errors: int
    usage_limit: int
    rejected: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_duration_ms: int


class ModelAlert(BaseModel):
    id: UUID
    level: Literal["amber", "red"]
    created_at: datetime
    acknowledged_at: datetime | None


class ModelUsage(BaseModel):
    window_days: int
    calls: int
    errors: int
    usage_limit: int
    rejected: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    usage_limit_last_hour: int
    rows: list[UsageRow]
    alerts: list[ModelAlert]


@router.get("/model-usage", response_model=ModelUsage)
async def model_usage(
    principal: PrincipalDep, session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> ModelUsage:
    require_roles(principal, *ADMIN_ROLES)
    rows = [UsageRow(**dict(r)) for r in (await session.execute(ROWS, {"days": days})).mappings()]
    last_hour = int((await session.execute(text(
        "SELECT count(*) FROM llm_calls WHERE status = 'usage_limit' "
        "AND created_at > now() - interval '1 hour'"))).scalar_one())
    alerts = await session.execute(text(
        "SELECT id, level, created_at, acknowledged_at FROM ops_alerts "
        "WHERE kind = 'model_usage_limit' ORDER BY created_at DESC"))
    return ModelUsage(
        window_days=days,
        calls=sum(r.calls for r in rows), errors=sum(r.errors for r in rows),
        usage_limit=sum(r.usage_limit for r in rows), rejected=sum(r.rejected for r in rows),
        input_tokens=sum(r.input_tokens for r in rows),
        output_tokens=sum(r.output_tokens for r in rows),
        cost_usd=round(sum(r.cost_usd for r in rows), 6),
        usage_limit_last_hour=last_hour, rows=rows,
        alerts=[ModelAlert(**dict(a)) for a in alerts.mappings()],
    )
