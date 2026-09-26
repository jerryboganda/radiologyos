"""Amber/red Voyage budget alerts to the tenant's admins (ADR 0019, ADR 0028).

``kind`` is ``embedding_budget`` or ``rerank_budget`` (each model has its own
free allowance and cap).

Each level is recorded once per tenant (``ops_alerts`` is unique on tenant,
kind, level); the first time it is recorded, every org_admin/superadmin push
subscription gets a notification with numbers only, and a log line records
the event. The admin UI shows a red or amber banner until acknowledged.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Literal
from uuid import UUID

from apps.worker.app.ingest.db import tenant_tx
from packages.models.routing import EmbeddingBudget
from packages.notifications import push
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.budget")


AlertKind = Literal["embedding_budget", "rerank_budget"]


def alert_payload(
    level: str, used: int, budget: EmbeddingBudget, kind: AlertKind = "embedding_budget"
) -> dict[str, str]:
    used_m = used / 1_000_000
    cap_m = budget.hard_cap_tokens / 1_000_000
    if kind == "rerank_budget":
        return _rerank_payload(level, used_m, cap_m)
    if level == "red":
        return {
            "title": "radbrain — embedding budget exhausted",
            "body": f"Voyage embedding stopped at {used_m:.1f}M of the {cap_m:.0f}M-token cap. "
                    "New documents stay keyword-searchable only.",
            "url": "/settings", "tag": "embedding-budget",
        }
    return {
        "title": "radbrain — embedding usage warning",
        "body": f"Voyage embedding has used {used_m:.1f}M of the {cap_m:.0f}M-token cap.",
        "url": "/settings", "tag": "embedding-budget",
    }


def _rerank_payload(level: str, used_m: float, cap_m: float) -> dict[str, str]:
    """ADR 0028: past the rerank cap, search keeps its fused (RRF) order."""
    if level == "red":
        return {
            "title": "radbrain — rerank budget exhausted",
            "body": f"Voyage reranking stopped at {used_m:.1f}M of the {cap_m:.0f}M-token cap. "
                    "Search and the tutor keep working in fused order.",
            "url": "/settings", "tag": "rerank-budget",
        }
    return {
        "title": "radbrain — rerank usage warning",
        "body": f"Voyage reranking has used {used_m:.1f}M of the {cap_m:.0f}M-token cap.",
        "url": "/settings", "tag": "rerank-budget",
    }


async def record_alert(
    engine: AsyncEngine, tenant_id: UUID, level: str, used: int, budget: EmbeddingBudget,
    kind: AlertKind = "embedding_budget",
) -> bool:
    """Record an alert level once and notify admins; returns True when new."""
    detail = {"tokens_used": used, "hard_cap_tokens": budget.hard_cap_tokens,
              "warn_tokens": budget.warn_tokens}
    async with tenant_tx(engine, tenant_id) as session:
        created = (
            await session.execute(
                text(
                    "INSERT INTO ops_alerts (tenant_id, kind, level, detail) "
                    "VALUES (:t, :k, :l, CAST(:d AS jsonb)) "
                    "ON CONFLICT (tenant_id, kind, level) DO NOTHING RETURNING id"
                ),
                {"t": tenant_id, "k": kind, "l": level, "d": json.dumps(detail)},
            )
        ).scalar_one_or_none()
        if created is None:
            return False
        subs = (
            await session.execute(
                text(
                    "SELECT ps.endpoint, ps.p256dh, ps.auth FROM push_subscriptions ps "
                    "JOIN memberships m ON m.tenant_id = ps.tenant_id AND m.user_id = ps.user_id "
                    "WHERE m.active AND m.deleted_at IS NULL "
                    "AND m.role IN ('org_admin', 'superadmin')"
                )
            )
        ).all()
    log.warning("%s_alert tenant=%s level=%s used=%s cap=%s",
                kind, tenant_id, level, used, budget.hard_cap_tokens)
    _notify(subs, alert_payload(level, used, budget, kind))
    return True


def _notify(subs: list[tuple[str, str, str]], payload: dict[str, str]) -> None:
    private = os.environ.get("VAPID_PRIVATE_KEY")
    if not private:
        return
    for endpoint, p256dh, auth in subs:
        try:
            push.send(push.Subscription(endpoint, p256dh, auth), payload, private)
        except (push.PushGone, push.PushFailed):
            continue
