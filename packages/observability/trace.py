"""Request/trace context carried through the API, worker tasks, and model calls.

Only stable identifiers live here: a request id (UUID), the tenant and user ids,
and the Celery task id. Content never does (hard rule 4). ``contextvars``
propagate into ``asyncio.to_thread`` / ``run_in_threadpool`` workers and into
tasks created by ``asyncio.run``, so a model call made from a thread still sees
the ids of the request or task that caused it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID, uuid4

_request_id: ContextVar[str | None] = ContextVar("radbrain_request_id", default=None)
_tenant_id: ContextVar[UUID | None] = ContextVar("radbrain_trace_tenant", default=None)
_user_id: ContextVar[UUID | None] = ContextVar("radbrain_trace_user", default=None)
_task_id: ContextVar[str | None] = ContextVar("radbrain_task_id", default=None)


@dataclass(frozen=True, slots=True)
class TraceContext:
    request_id: str | None
    tenant_id: UUID | None
    user_id: UUID | None
    task_id: str | None


def coerce_request_id(value: str | None) -> str:
    """A caller-supplied id when it is a UUID, else a fresh one (never echo junk)."""
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


def as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def current() -> TraceContext:
    return TraceContext(_request_id.get(), _tenant_id.get(), _user_id.get(), _task_id.get())


def request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def set_identity(tenant_id: UUID | None, user_id: UUID | None) -> None:
    """Record who the current request or task acts for (ids only)."""
    _tenant_id.set(tenant_id)
    _user_id.set(user_id)


def set_task(task_id: str | None, tenant_id: UUID | None) -> None:
    _task_id.set(task_id)
    _tenant_id.set(tenant_id)
    _user_id.set(None)


@contextmanager
def bound(
    request_id: str | None = None, tenant_id: UUID | None = None,
    user_id: UUID | None = None, task_id: str | None = None,
) -> Iterator[None]:
    """Bind ids for a block and restore the previous values afterwards."""
    tokens = (_request_id.set(request_id), _tenant_id.set(tenant_id),
              _user_id.set(user_id), _task_id.set(task_id))
    try:
        yield
    finally:
        _task_id.reset(tokens[3])
        _user_id.reset(tokens[2])
        _tenant_id.reset(tokens[1])
        _request_id.reset(tokens[0])
