"""Daily study reminders over Web Push (owner requirement, ADR 0011).

Celery beat runs ``radbrain.send_due_reminders`` every few minutes. The narrow
``app.due_reminders`` resolver returns only (tenant, user) ids whose local
reminder time has passed today; everything else is read under that tenant's
RLS context. Payloads carry counts only, never study content.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.worker.app.celery_app import celery_app
from apps.worker.app.ingest.db import make_engine, tenant_tx
from packages.notifications import push
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

log = logging.getLogger("radbrain.reminders")


@celery_app.task(name="radbrain.send_due_reminders")  # type: ignore[untyped-decorator]
def send_due_reminders() -> int:
    private = os.environ.get("VAPID_PRIVATE_KEY")
    if not private:
        return 0

    async def run() -> int:
        engine = make_engine()
        try:
            return await _send_all(engine, private)
        finally:
            await engine.dispose()

    return asyncio.run(run())


async def _send_all(engine: AsyncEngine, private: str) -> int:
    async with AsyncSession(engine) as session:
        due = (
            await session.execute(
                text("SELECT tenant_id, user_id FROM app.due_reminders(:now)"),
                {"now": datetime.now(UTC)},
            )
        ).all()
    sent = 0
    for tenant_id, user_id in due:
        sent += await _remind(engine, UUID(str(tenant_id)), UUID(str(user_id)), private)
    if due:
        log.info("reminders users=%s pushes=%s", len(due), sent)
    return sent


async def _remind(engine: AsyncEngine, tenant_id: UUID, user_id: UUID, private: str) -> int:
    async with tenant_tx(engine, tenant_id) as session:
        subs = (
            await session.execute(
                text("SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
                     "WHERE user_id = :u"),
                {"u": user_id},
            )
        ).mappings().all()
        facts = await _facts(session, user_id)
        await session.execute(
            text(
                "UPDATE notification_settings SET last_sent_on = "
                "(now() AT TIME ZONE timezone)::date WHERE user_id = :u"
            ),
            {"u": user_id},
        )
    payload = push.reminder_payload(**facts)
    sent, gone = 0, []
    for row in subs:
        try:
            push.send(push.Subscription(row["endpoint"], row["p256dh"], row["auth"]), payload,
                      private)
            sent += 1
        except push.PushGone:
            gone.append(row["id"])
        except push.PushFailed:
            continue
    if gone:
        async with tenant_tx(engine, tenant_id) as session:
            await session.execute(text("DELETE FROM push_subscriptions WHERE id = ANY(:ids)"),
                                  {"ids": gone})
    return sent


async def _facts(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    facts: dict[str, Any] = {"due_cards": None, "days_to_exam": None, "plan_minutes": None}
    tables = (
        await session.execute(
            text("SELECT to_regclass('public.cards') IS NOT NULL, "
                 "to_regclass('public.study_profiles') IS NOT NULL")
        )
    ).one()
    if tables[0]:
        facts["due_cards"] = (
            await session.execute(
                text("SELECT count(*) FROM cards WHERE user_id = :u AND due_at <= now()"),
                {"u": user_id},
            )
        ).scalar_one()
    if tables[1]:
        profile = (
            await session.execute(
                text("SELECT exam_date, daily_minutes FROM study_profiles WHERE user_id = :u"),
                {"u": user_id},
            )
        ).first()
        if profile is not None:
            if profile[0] is not None:
                facts["days_to_exam"] = max((profile[0] - datetime.now(UTC).date()).days, 0)
            facts["plan_minutes"] = profile[1]
    return facts
