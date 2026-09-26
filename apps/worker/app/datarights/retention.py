"""Scheduled retention purge of uploaded sources (ADR 0009, ADR 0020).

``RETENTION_PURGE_MODE`` selects the behaviour and defaults to ``off``:

* ``off``      - nothing is read or changed;
* ``dry_run``  - one ``retention.dry_run`` audit row per tenant with the count
  of due sources; nothing is deleted;
* ``enforce``  - each due source is purged like a user delete (object prefix,
  then the shared per-source purge), with one ``retention.source_purged``
  audit row. Every source is its own transaction, so a crashed run resumes by
  simply running again.

Due sources come from the ids-only ``app.retention_due_sources``, which never
returns legal-hold, Core, or exempt-tenant sources; the hold is re-checked
under a row lock before anything is deleted. ``RETENTION_DEFAULT_MONTHS``
(default 24) applies unless a tenant sets ``settings.retention_months``
(``0`` exempts it). Only ids and counts are stored or logged (hard rule 4).

Manual dry run (never deletes): ``python -m apps.worker.app.datarights.retention``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.api.app.library.service import purge_source_rows
from apps.worker.app.datarights import jobs
from apps.worker.app.ingest.db import tenant_tx
from packages.library import storage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("radbrain.retention")
MODES = ("off", "dry_run", "enforce")
DEFAULT_MONTHS = 24
Due = tuple[UUID, UUID, int]


def configured_mode() -> str:
    mode = os.environ.get("RETENTION_PURGE_MODE", "off").strip().lower()
    if mode not in MODES:
        log.warning("unknown RETENTION_PURGE_MODE; retention stays off")
        return "off"
    return mode


def configured_months() -> int:
    raw = os.environ.get("RETENTION_DEFAULT_MONTHS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_MONTHS


async def due_sources(deps: jobs.DataDeps, now: datetime, months: int) -> list[Due]:
    async with AsyncSession(deps.engine) as session:
        rows: Sequence[Any] = (
            await session.execute(
                text("SELECT tenant_id, source_id, months "
                     "FROM app.retention_due_sources(:now, :months)"),
                {"now": now, "months": months},
            )
        ).all()
    return [(UUID(str(t)), UUID(str(s)), int(m)) for t, s, m in rows]


async def sweep(
    deps: jobs.DataDeps, now: datetime, mode: str, months: int = DEFAULT_MONTHS
) -> dict[str, int]:
    """Run one retention pass; returns counts only."""
    if mode not in ("dry_run", "enforce"):
        return {"due": 0, "purged": 0}
    found = await due_sources(deps, now, months)
    if mode == "dry_run":
        await _record_dry_run(deps, found)
        return {"due": len(found), "purged": 0}
    purged = 0
    for tenant, source, tenant_months in found:
        purged += await _purge(deps, tenant, source, tenant_months)
    if found:
        log.info("retention due=%s purged=%s", len(found), purged)
    return {"due": len(found), "purged": purged}


async def _record_dry_run(deps: jobs.DataDeps, found: list[Due]) -> None:
    per_tenant = Counter(tenant for tenant, _, _ in found)
    months = {tenant: m for tenant, _, m in found}
    for tenant, count in per_tenant.items():
        async with tenant_tx(deps.engine, tenant) as session:
            await _audit(session, tenant, "retention.dry_run", "tenant", str(tenant),
                         {"due_sources": count, "months": months[tenant]})


async def _purge(deps: jobs.DataDeps, tenant: UUID, source: UUID, months: int) -> int:
    async with tenant_tx(deps.engine, tenant) as session:
        held: Any = (
            await session.execute(
                text("SELECT legal_hold FROM sources WHERE id = :id FOR UPDATE"),
                {"id": source},
            )
        ).scalar_one_or_none()
        if held is None or held:
            return 0
        # Objects first: a crash after this leaves rows that the next run
        # purges again, never unreachable orphan objects.
        deps.store.delete_prefix(storage.source_prefix(tenant, source) + "/")
        await purge_source_rows(session, source)
        await _audit(session, tenant, "retention.source_purged", "source", str(source),
                     {"months": months})
    return 1


async def _audit(session: AsyncSession, tenant: UUID, action: str, target_type: str,
                 target_id: str, metadata: dict[str, Any]) -> None:
    await session.execute(
        text("INSERT INTO audit_log (tenant_id, actor_user_id, action, target_type, "
             "target_id, metadata) VALUES (:t, NULL, :a, :tt, :tid, CAST(:m AS jsonb))"),
        {"t": tenant, "a": action, "tt": target_type, "tid": target_id,
         "m": json.dumps(metadata)},
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Dry run only: deleting happens solely through the scheduled task."""
    parser = argparse.ArgumentParser(description="Report sources past retention (dry run).")
    parser.add_argument("--months", type=int, default=configured_months())
    args = parser.parse_args(argv)

    async def run() -> dict[str, int]:
        from apps.worker.app.datarights.tasks import build_data_deps

        deps = build_data_deps()
        try:
            return await sweep(deps, datetime.now(UTC), "dry_run", args.months)
        finally:
            await deps.engine.dispose()

    print(json.dumps(asyncio.run(run())))


if __name__ == "__main__":
    main()
