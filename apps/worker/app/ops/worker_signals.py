"""Celery signal hooks: trace ids across the broker, worker log context, ledger (ADR 0032).

* Publishing a task (from the API or another task) adds the current request id
  as the ``radbrain_request_id`` message header.
* Before a task runs, its task id, the tenant id (every tenant task takes it as
  the first argument), and that request id are bound in ``packages.observability.
  trace``; model-call ledger rows and log lines then carry them.
* Each worker process installs the ``llm_calls`` sink after fork.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from celery import signals
from packages.observability import trace

HEADER = "radbrain_request_id"
LOG_FORMAT = ("%(asctime)s %(levelname)s %(name)s task=%(trace_task)s "
              "tenant=%(trace_tenant)s request=%(trace_request)s %(message)s")


class TraceFilter(logging.Filter):
    """Adds the current task, tenant, and request ids to every record (ids only)."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = trace.current()
        record.trace_task = ctx.task_id or "-"
        record.trace_tenant = str(ctx.tenant_id) if ctx.tenant_id else "-"
        record.trace_request = ctx.request_id or "-"
        return True


def tenant_argument(args: Any, kwargs: Any) -> Any:
    if isinstance(kwargs, dict) and "tenant_id" in kwargs:
        return trace.as_uuid(kwargs["tenant_id"])
    if isinstance(args, list | tuple) and args:
        return trace.as_uuid(args[0])
    return None


def request_header(task: Any) -> str | None:
    request = getattr(task, "request", None)
    value = getattr(request, HEADER, None)
    if value is None:
        headers = getattr(request, "headers", None)
        value = headers.get(HEADER) if isinstance(headers, dict) else None
    return trace.coerce_request_id(str(value)) if value else None


def add_request_header(headers: dict[str, Any] | None = None, **_: Any) -> None:
    rid = trace.request_id()
    if rid and isinstance(headers, dict):
        headers.setdefault(HEADER, rid)


def bind_task(task_id: str | None = None, task: Any = None, args: Any = None,
              kwargs: Any = None, **_: Any) -> None:
    trace.set_task(task_id, tenant_argument(args, kwargs))
    trace.set_request_id(request_header(task))


def unbind_task(**_: Any) -> None:
    trace.set_task(None, None)
    trace.set_request_id(None)


def _add_filter(logger: logging.Logger, **_: Any) -> None:
    for handler in logger.handlers:
        if not any(isinstance(f, TraceFilter) for f in handler.filters):
            handler.addFilter(TraceFilter())
            handler.setFormatter(logging.Formatter(LOG_FORMAT))


def trace_root_logger(logger: logging.Logger, **kwargs: Any) -> None:
    _add_filter(logger, **kwargs)


def trace_task_logger(logger: logging.Logger, **kwargs: Any) -> None:
    _add_filter(logger, **kwargs)


def install_ledger(**_: Any) -> None:
    """Idempotent; the sink starts its writer lazily in whichever process records."""
    from apps.worker.app.ops.llm_ledger import install

    install(os.environ.get("DATABASE_URL"))


def connect() -> None:
    """Attach the handlers (strong references; safe to call more than once)."""
    for signal, handler in (
        (signals.before_task_publish, add_request_header),
        (signals.task_prerun, bind_task),
        (signals.task_postrun, unbind_task),
        (signals.after_setup_logger, trace_root_logger),
        (signals.after_setup_task_logger, trace_task_logger),
        (signals.worker_init, install_ledger),
        (signals.worker_process_init, install_ledger),
    ):
        signal.connect(handler, weak=False, dispatch_uid=f"radbrain-{handler.__name__}")


connect()
