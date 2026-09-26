"""Pause checks and the quota pause for worker pipelines (ADR 0037).

Every pipeline checks ``paused()`` before each unit of model work, so the
owner's pause and a quota pause both stop between saved units. The first
process to hit a provider's quota records the pause for all workers (Redis)
and queues one alert to the owner; later hits in the same window stay quiet.
Works from synchronous model-call code (the knowledge agents) as well as async.
"""

from __future__ import annotations

import logging

from packages.models.claude_code import UsageLimitError
from packages.observability import trace
from packages.pipeline import state

log = logging.getLogger("radbrain.pausing")


def paused() -> bool:
    return state.current().paused


def quota_hit(exc: UsageLimitError) -> None:
    """Pause every worker until the provider's reset; alert the owner once."""
    try:
        until = state.quota_hit(exc.provider, exc.retry_after_s)
    except Exception as err:  # the task still defers on its own default delay
        log.warning("quota_pause_record_failed error=%s", type(err).__name__)
        return
    tenant = trace.current().tenant_id
    if until is None or tenant is None:
        return
    from apps.worker.app.tasks import quota_alert

    try:
        quota_alert.delay(str(tenant), exc.provider, until)
    except Exception as err:  # the pause matters more than the alert
        log.warning("quota_alert_enqueue_failed error=%s", type(err).__name__)


def recheck_in() -> int | None:
    """Seconds a deferred task should wait, or None when nothing is paused."""
    current = state.current()
    return current.recheck_in() if current.paused else None


def defer_delay(default_s: int) -> int:
    """How long a deferred task waits: until the pause ends, else the default."""
    return recheck_in() or default_s
