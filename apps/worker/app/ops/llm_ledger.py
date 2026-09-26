"""Persist model-call records to ``llm_calls`` and alert on usage-limit spikes (ADR 0032).

The gateway emits records synchronously from whatever thread made the call —
an API threadpool worker, or a Celery task inside ``asyncio.run``. Writing
from there would tie the ledger to that thread's event loop, so ``LedgerSink``
queues records and a daemon thread with its own loop and engine (NullPool)
writes them, each in the record's tenant transaction (RLS). A record without a
tenant (no request or task identity) is counted in metrics but not stored. The
queue is bounded; when it is full a record is dropped and logged once.

When one tenant sees more than ``MODEL_USAGE_LIMIT_ALERT_PER_HOUR`` (default 5)
usage-limit errors within an hour, an amber ``model_usage_limit`` alert is
raised once and pushed to the tenant's admins; after it is acknowledged, the
next spike an hour or more later raises it again.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import queue
import threading
from typing import Any
from uuid import UUID

from apps.worker.app.ingest.budget_alerts import admin_subscriptions, notify
from apps.worker.app.ingest.db import tenant_tx
from packages.models import ledger
from packages.observability import metrics
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

log = logging.getLogger("radbrain.ledger")
MODEL_CALLS = "radbrain_model_calls_total"
MODEL_SECONDS = "radbrain_model_call_seconds_total"
ALERT_PAYLOAD = {
    "title": "radbrain — model usage window exhausted",
    "body": "Model calls are hitting the subscription usage limit. Ingest and "
            "generation pause and resume when the window resets.",
    "url": "/settings", "tag": "model-usage-limit",
}


def alert_threshold() -> int:
    try:
        return max(1, int(os.environ.get("MODEL_USAGE_LIMIT_ALERT_PER_HOUR", "5")))
    except ValueError:
        return 5


def count_call(record: ledger.CallRecord) -> None:
    """Recorder: platform-wide outcome counters (no tenant labels)."""
    labels = {"agent": record.agent, "backend": record.backend, "status": record.status}
    shared = metrics.shared()
    shared.inc(MODEL_CALLS, labels)
    shared.inc(MODEL_SECONDS, labels, record.duration_ms / 1000)


async def insert_call(session: AsyncSession, record: ledger.CallRecord) -> None:
    await session.execute(
        text(
            "INSERT INTO llm_calls (tenant_id, user_id, request_id, agent, route, backend, "
            "model, effort, status, error_code, duration_ms, input_tokens, output_tokens, "
            "cost_usd) VALUES (:t, :u, :rid, :agent, :route, :backend, :model, :effort, "
            ":status, :code, :ms, :tin, :tout, :cost)"
        ),
        {"t": record.tenant_id, "u": record.user_id,
         "rid": ledger_request_id(record.request_id), "agent": record.agent[:80],
         "route": record.route, "backend": record.backend[:40], "model": record.model[:100],
         "effort": record.effort, "status": record.status,
         "code": (record.error_code or None) and record.error_code[:80],
         "ms": max(0, record.duration_ms), "tin": record.input_tokens,
         "tout": record.output_tokens, "cost": record.cost_usd},
    )


def ledger_request_id(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


async def raise_spike_alert(session: AsyncSession, tenant_id: UUID, threshold: int) -> bool:
    """Record (or re-arm) the amber alert when the last hour passed the threshold."""
    recent = int((await session.execute(
        text("SELECT count(*) FROM llm_calls WHERE status = 'usage_limit' "
             "AND created_at > now() - interval '1 hour'"))).scalar_one())
    if recent <= threshold:
        return False
    detail = json.dumps({"usage_limit_last_hour": recent, "threshold": threshold})
    created = (await session.execute(
        text(
            "INSERT INTO ops_alerts (tenant_id, kind, level, detail) "
            "VALUES (:t, 'model_usage_limit', 'amber', CAST(:d AS jsonb)) "
            "ON CONFLICT (tenant_id, kind, level) DO UPDATE SET detail = EXCLUDED.detail, "
            "created_at = now(), acknowledged_at = NULL, acknowledged_by = NULL "
            "WHERE ops_alerts.acknowledged_at IS NOT NULL "
            "AND ops_alerts.acknowledged_at < now() - interval '1 hour' RETURNING id"
        ),
        {"t": tenant_id, "d": detail},
    )).scalar_one_or_none()
    return created is not None


async def store(engine: AsyncEngine, record: ledger.CallRecord, threshold: int) -> None:
    """Write one record; on a usage-limit record, check for a spike."""
    if record.tenant_id is None:
        return
    subs: list[tuple[str, str, str]] = []
    alerted = False
    async with tenant_tx(engine, record.tenant_id) as session:
        await insert_call(session, record)
        if record.status == "usage_limit":
            alerted = await raise_spike_alert(session, record.tenant_id, threshold)
            if alerted:
                subs = await admin_subscriptions(session)
    if alerted:
        log.warning("model_usage_limit_alert tenant=%s", record.tenant_id)
        notify(subs, ALERT_PAYLOAD)


class LedgerSink:
    """Queue records and write them from one background thread per process."""

    def __init__(self, database_url: str, maxsize: int = 2000) -> None:
        self._url = database_url
        self._queue: queue.Queue[ledger.CallRecord | None] = queue.Queue(maxsize=maxsize)
        self._thread: threading.Thread | None = None
        self._pid = 0
        self._lock = threading.Lock()
        self._dropped = False

    def __call__(self, record: ledger.CallRecord) -> None:
        self._ensure_thread()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            if not self._dropped:
                self._dropped = True
                log.warning("ledger_queue_full action=drop")

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._pid == os.getpid():
                return
            self._pid = os.getpid()  # a forked child needs its own writer
            self._thread = threading.Thread(target=self._run, name="llm-ledger", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        """Block on the queue in this daemon thread; write each record on its own loop.

        The blocking ``get`` runs here, not in an executor thread, so a waiting
        writer never holds up interpreter shutdown.
        """
        threshold = alert_threshold()
        with asyncio.Runner() as runner:
            engine = create_async_engine(self._url, poolclass=NullPool)
            try:
                while (record := self._queue.get()) is not None:
                    try:
                        runner.run(store(engine, record, threshold))
                    except Exception as exc:  # never kill the writer
                        log.warning("ledger_write_failed error=%s", type(exc).__name__)
                    finally:
                        self._queue.task_done()
                self._queue.task_done()
            finally:
                runner.run(engine.dispose())

    def flush(self, timeout_s: float = 5.0) -> None:
        """Wait (bounded) until queued records are written."""
        done = threading.Event()

        def wait() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=wait, daemon=True).start()
        done.wait(timeout_s)


_installed: dict[str, Any] = {}


def install(database_url: str | None) -> None:
    """Register the metrics recorder and (with a database URL) the ledger sink."""
    if _installed:
        return
    ledger.add_recorder(count_call)
    _installed["metrics"] = count_call
    if database_url:
        sink = LedgerSink(database_url)
        ledger.add_recorder(sink)
        _installed["sink"] = sink
        atexit.register(sink.flush, 2.0)
