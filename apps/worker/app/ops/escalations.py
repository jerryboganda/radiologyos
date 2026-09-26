"""Collect & ask (ADR 0037): items waiting for the owner's approval of Claude Opus.

When GPT-6 Luna and Sol both fail an item, or both answer it below a quality
gate, the item is saved here and the run moves on. The owner approves the list
in one go (Settings, or the pipeline CLI); approved items are then redone on
Claude Opus 5.5 high only. The table holds ids, agent names, and fixed reason
strings - never source text (hard rule 4).

This module also raises the owner's alerts for the pipeline: the ChatGPT quota
pause (red) and "items are waiting for your approval" (amber), each pushed to
the tenant's admins once.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.worker.app.ingest.budget_alerts import admin_subscriptions, notify
from apps.worker.app.ingest.db import tenant_tx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

log = logging.getLogger("radbrain.escalations")


async def record(
    session: AsyncSession, tenant_id: UUID, source_id: UUID, agent: str, unit: str,
    reason: str,
) -> bool:
    """Save one item for approval; True when it is new (a pending item stays as is)."""
    created = (await session.execute(
        text(
            "INSERT INTO model_escalations (tenant_id, source_id, agent, unit, reason) "
            "VALUES (:t, :s, :a, :u, :r) ON CONFLICT (tenant_id, source_id, agent, unit) "
            "DO UPDATE SET status = 'pending', reason = EXCLUDED.reason, resolved_at = NULL "
            "WHERE model_escalations.status IN ('done', 'dismissed') RETURNING id"
        ),
        {"t": tenant_id, "s": source_id, "a": agent[:80], "u": unit[:120], "r": reason[:80]},
    )).scalar_one_or_none()
    return created is not None


async def approved_units(session: AsyncSession, source_id: UUID, agent: str) -> set[str]:
    rows = await session.execute(
        text("SELECT unit FROM model_escalations WHERE source_id = :s AND agent = :a "
             "AND status = 'approved'"),
        {"s": source_id, "a": agent},
    )
    return {str(r["unit"]) for r in rows.mappings()}


async def mark_done(session: AsyncSession, source_id: UUID, agent: str, unit: str) -> None:
    await session.execute(
        text("UPDATE model_escalations SET status = 'done', resolved_at = now() "
             "WHERE source_id = :s AND agent = :a AND unit = :u AND status = 'approved'"),
        {"s": source_id, "a": agent, "u": unit},
    )


async def escalate(
    engine: AsyncEngine, tenant_id: UUID, source_id: UUID, agent: str, unit: str,
    reason: str,
) -> None:
    """Record the item and, when it is the first of a new batch, tell the owner."""
    async with tenant_tx(engine, tenant_id) as session:
        if not await record(session, tenant_id, source_id, agent, unit, reason):
            return
        pending = int((await session.execute(text(
            "SELECT count(*) FROM model_escalations WHERE status = 'pending'"))).scalar_one())
        alerted = await _upsert_alert(session, tenant_id, "owner_approval", "amber",
                                      {"pending": pending})
        subs = await admin_subscriptions(session) if alerted else []
    log.info("escalation agent=%s reason=%s source=%s", agent, reason, source_id)
    if alerted:
        notify(subs, {
            "title": "radbrain — items need your approval",
            "body": "Some pages or notes could not be read well by GPT-6 Luna or Sol. "
                    "They are saved; approve them in Settings to redo them on Claude Opus.",
            "url": "/settings", "tag": "owner-approval"})


async def quota_paused(
    engine: AsyncEngine, tenant_id: UUID, provider: str, until: float
) -> None:
    """Red alert and push: the pipeline is paused until the provider's reset."""
    resume = datetime.fromtimestamp(until, UTC).strftime("%H:%M UTC")
    async with tenant_tx(engine, tenant_id) as session:
        alerted = await _upsert_alert(session, tenant_id, "chatgpt_quota", "red",
                                      {"provider": provider, "resume_at": int(until)},
                                      rearm=True)
        subs = await admin_subscriptions(session) if alerted else []
    log.warning("quota_pause provider=%s until=%s", provider, int(until))
    notify(subs, {
        "title": f"radbrain — {'ChatGPT' if provider == 'chatgpt' else provider} quota reached",
        "body": f"Library processing is paused and resumes by itself at about {resume}. "
                "Nothing is lost; it continues where it stopped.",
        "url": "/settings", "tag": "chatgpt-quota"})


async def _upsert_alert(
    session: AsyncSession, tenant_id: UUID, kind: str, level: str, detail: dict[str, Any],
    rearm: bool = False,
) -> bool:
    """Create the alert, or re-open an acknowledged one; True when the owner should hear."""
    condition = ("ops_alerts.acknowledged_at IS NOT NULL" if not rearm
                 else "TRUE")
    created = (await session.execute(
        text(
            "INSERT INTO ops_alerts (tenant_id, kind, level, detail) "
            "VALUES (:t, :k, :l, CAST(:d AS jsonb)) "
            "ON CONFLICT (tenant_id, kind, level) DO UPDATE SET detail = EXCLUDED.detail, "
            "created_at = now(), acknowledged_at = NULL, acknowledged_by = NULL "
            f"WHERE {condition} RETURNING id"  # nosec B608 - two constant predicates
        ),
        {"t": tenant_id, "k": kind, "l": level, "d": json.dumps(detail)},
    )).scalar_one_or_none()
    return created is not None
