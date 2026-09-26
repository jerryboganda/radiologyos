"""Admin view of the Voyage embedding budget and its alerts (ADR 0019)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, HTTPException, status
from packages.models.budget import BudgetState, billed_estimate_usd, list_price_usd
from packages.models.routing import FREE_TIER_TOKENS
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/admin", tags=["admin"])
PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
ADMIN_ROLES = ("org_admin", "superadmin")


class BudgetAlert(BaseModel):
    id: UUID
    level: Literal["amber", "red"]
    created_at: datetime
    acknowledged_at: datetime | None


class EmbeddingUsage(BaseModel):
    document_model: str
    query_model: str
    tokens_used: int
    hard_cap_tokens: int
    warn_tokens: int
    free_tier_tokens: int
    free_tier_remaining: int
    status: Literal["ok", "amber", "red"]
    list_price_usd_equivalent: float
    billed_estimate_usd: float
    alerts: list[BudgetAlert]


@router.get("/embedding-usage", response_model=EmbeddingUsage)
async def embedding_usage(principal: PrincipalDep, session: SessionDep) -> EmbeddingUsage:
    require_roles(principal, *ADMIN_ROLES)
    from packages.models.gateway import routing_config

    config = routing_config().embeddings
    if config is None:
        raise HTTPException(status_code=404, detail="embeddings are not configured")
    used = int((await session.execute(text("SELECT app.embedding_tokens_total()"))).scalar_one())
    rows = await session.execute(
        text("SELECT id, level, created_at, acknowledged_at FROM ops_alerts "
             "WHERE kind = 'embedding_budget' ORDER BY created_at DESC")
    )
    state = BudgetState(used, config.budget)
    model = config.document.model
    return EmbeddingUsage(
        document_model=model,
        query_model=config.query.model,
        tokens_used=used,
        hard_cap_tokens=config.budget.hard_cap_tokens,
        warn_tokens=config.budget.warn_tokens,
        free_tier_tokens=FREE_TIER_TOKENS,
        free_tier_remaining=state.free_tier_remaining,
        status=state.level,
        list_price_usd_equivalent=list_price_usd(used, model),
        billed_estimate_usd=billed_estimate_usd(used, model),
        alerts=[BudgetAlert(**dict(row)) for row in rows.mappings()],
    )


@router.post("/alerts/{alert_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_alert(alert_id: UUID, principal: PrincipalDep, session: SessionDep) -> None:
    require_roles(principal, *ADMIN_ROLES)
    updated = (
        await session.execute(
            text("UPDATE ops_alerts SET acknowledged_at = now(), acknowledged_by = :u "
                 "WHERE id = :id AND acknowledged_at IS NULL RETURNING id"),
            {"id": alert_id, "u": principal.user_id},
        )
    ).scalar_one_or_none()
    if updated is None:
        exists = (await session.execute(text("SELECT 1 FROM ops_alerts WHERE id = :id"),
                                        {"id": alert_id})).scalar_one_or_none()
        if exists is None:
            raise HTTPException(status_code=404, detail="alert not found")
    await session.commit()
