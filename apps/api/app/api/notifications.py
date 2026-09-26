"""Push reminder API: VAPID key, subscriptions, settings, and a test push."""

from __future__ import annotations

import os
from datetime import time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from packages.notifications import push
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/notifications", tags=["notifications"])
PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]


class VapidKey(BaseModel):
    public_key: str | None
    enabled: bool


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(pattern=r"^https://", max_length=2047)
    p256dh: str = Field(min_length=16, max_length=255)
    auth: str = Field(min_length=8, max_length=127)
    user_agent: str | None = Field(default=None, max_length=300)


class SubscriptionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=2047)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    reminder_time: time = time(19, 0)
    timezone: str = "Asia/Karachi"
    channels: list[Literal["push", "email"]] = ["push"]
    include_due_cards: bool = True
    include_plan: bool = True

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value


@router.get("/vapid-public-key", response_model=VapidKey)
async def vapid_public_key(principal: PrincipalDep) -> VapidKey:
    key = os.environ.get("VAPID_PUBLIC_KEY") or None
    return VapidKey(public_key=key, enabled=bool(key and os.environ.get("VAPID_PRIVATE_KEY")))


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(body: SubscriptionIn, principal: PrincipalDep, session: SessionDep) -> None:
    await session.execute(
        text(
            "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth, "
            "user_agent) VALUES (:t, :u, :e, :p, :a, :ua) ON CONFLICT (tenant_id, endpoint) "
            "DO UPDATE SET user_id = EXCLUDED.user_id, p256dh = EXCLUDED.p256dh, "
            "auth = EXCLUDED.auth, failures = 0"
        ),
        {"t": principal.tenant_id, "u": principal.user_id, "e": body.endpoint,
         "p": body.p256dh, "a": body.auth, "ua": body.user_agent},
    )
    await _ensure_settings(session, principal)
    await session.commit()


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(body: SubscriptionRef, principal: PrincipalDep, session: SessionDep) -> None:
    await session.execute(
        text("DELETE FROM push_subscriptions WHERE endpoint = :e AND user_id = :u"),
        {"e": body.endpoint, "u": principal.user_id},
    )
    await session.commit()


@router.get("/settings", response_model=Settings)
async def get_settings_route(principal: PrincipalDep, session: SessionDep) -> Settings:
    row = (
        await session.execute(
            text(
                "SELECT enabled, reminder_time, timezone, channels, include_due_cards, "
                "include_plan FROM notification_settings WHERE user_id = :u"
            ),
            {"u": principal.user_id},
        )
    ).mappings().first()
    return Settings(**row) if row else Settings()


@router.put("/settings", response_model=Settings)
async def put_settings(body: Settings, principal: PrincipalDep, session: SessionDep) -> Settings:
    import json

    await session.execute(
        text(
            """
            INSERT INTO notification_settings (tenant_id, user_id, enabled, reminder_time,
                timezone, channels, include_due_cards, include_plan)
            VALUES (:t, :u, :enabled, :time, :tz, CAST(:channels AS jsonb), :cards, :plan)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET enabled = EXCLUDED.enabled,
                reminder_time = EXCLUDED.reminder_time, timezone = EXCLUDED.timezone,
                channels = EXCLUDED.channels, include_due_cards = EXCLUDED.include_due_cards,
                include_plan = EXCLUDED.include_plan, last_sent_on = NULL
            """
        ),
        {"t": principal.tenant_id, "u": principal.user_id, "enabled": body.enabled,
         "time": body.reminder_time, "tz": body.timezone, "channels": json.dumps(body.channels),
         "cards": body.include_due_cards, "plan": body.include_plan},
    )
    await session.commit()
    return body


@router.post("/test", status_code=status.HTTP_202_ACCEPTED)
async def test_push(principal: PrincipalDep, session: SessionDep) -> dict[str, int]:
    private = os.environ.get("VAPID_PRIVATE_KEY")
    if not private:
        raise HTTPException(status_code=503, detail="push is not configured on this server")
    rows = (
        await session.execute(
            text("SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = :u"),
            {"u": principal.user_id},
        )
    ).mappings().all()
    payload = {"title": "radbrain", "body": "Test reminder — notifications work.", "url": "/"}
    sent, gone = 0, []
    for row in rows:
        sub = push.Subscription(row["endpoint"], row["p256dh"], row["auth"])
        try:
            await run_in_threadpool(push.send, sub, payload, private)
            sent += 1
        except push.PushGone:
            gone.append(row["id"])
        except push.PushFailed:
            continue
    if gone:
        await session.execute(text("DELETE FROM push_subscriptions WHERE id = ANY(:ids)"),
                              {"ids": gone})
        await session.commit()
    return {"sent": sent, "removed": len(gone)}


async def _ensure_settings(session: AsyncSession, principal: Principal) -> None:
    await session.execute(
        text(
            "INSERT INTO notification_settings (tenant_id, user_id) VALUES (:t, :u) "
            "ON CONFLICT (tenant_id, user_id) DO NOTHING"
        ),
        {"t": principal.tenant_id, "u": principal.user_id},
    )

