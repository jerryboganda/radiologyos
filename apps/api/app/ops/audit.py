"""Audit rows for every mutating API request (ADR 0032, hard rule 4).

Two layers write ``audit_log``:

* ``audit(session, principal, ...)`` - a named, domain-specific event inside the
  request's own transaction (``source.uploaded``, ``question.review_approve``,
  ...). It stamps the request id and marks the request as audited.
* ``request_audit`` - called by the request middleware after every successful
  POST/PUT/PATCH/DELETE under the API prefix that no named event covered. It
  writes one ``api.<method>`` row in its own short tenant transaction with the
  route template, status code, and the id path parameter; never a body.

Both hold ids only; metadata is route templates, counts, and hashes. A failed
generic write is logged once by error class and never fails the response.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from apps.api.app.security.principal import Principal
from packages.observability import trace
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("radbrain.api")
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# POST routes that change nothing (queries sent as bodies).
READ_ONLY_POSTS = frozenset({"/v1/library/search", "/v1/tenants/switch"})
# No principal, or no durable state: preview is in-memory; the Stripe webhook is
# signed by Stripe and audited by the billing service.
EXEMPT_PREFIXES = ("/v1/preview", "/v1/billing/webhook")
INSERT = text(
    "INSERT INTO audit_log (tenant_id, actor_user_id, action, target_type, target_id, "
    "request_id, metadata) VALUES (:t, :u, :a, :tt, :tid, :rid, CAST(:m AS jsonb))"
)


@dataclass(slots=True)
class AuditScope:
    """Per-request state shared between the middleware and the endpoint task."""

    named_events: int = 0
    notes: dict[str, Any] = field(default_factory=dict)


_scope: ContextVar[AuditScope | None] = ContextVar("radbrain_audit_scope", default=None)


def open_scope() -> AuditScope:
    scope = AuditScope()
    _scope.set(scope)
    return scope


def _request_uuid() -> UUID | None:
    rid = trace.request_id()
    try:
        return UUID(rid) if rid else None
    except ValueError:
        return None


async def audit(
    session: AsyncSession, principal: Principal, action: str, target_type: str,
    target_id: str, metadata: dict[str, Any] | None = None,
) -> None:
    """A named audit event in the caller's transaction (ids and numbers only)."""
    await session.execute(
        INSERT,
        {"t": principal.tenant_id, "u": principal.user_id, "a": action, "tt": target_type,
         "tid": target_id, "rid": _request_uuid(), "m": json.dumps(metadata or {})},
    )
    scope = _scope.get()
    if scope is not None:
        scope.named_events += 1


@dataclass(frozen=True, slots=True)
class Mutation:
    tenant_id: UUID
    user_id: UUID
    method: str
    route: str
    status_code: int
    path_params: Mapping[str, str]

    @property
    def action(self) -> str:
        return f"api.{self.method.lower()}"

    def target(self) -> tuple[str, str | None]:
        """(type, id) from the last ``*_id`` path parameter, else the route's area."""
        ids = [(k, v) for k, v in self.path_params.items() if k.endswith("_id")]
        if ids:
            name, value = ids[-1]
            return name[: -len("_id")], value[:200]
        parts = [p for p in self.route.split("/") if p and not p.startswith("{")]
        return (parts[1] if len(parts) > 1 else "api"), None


def should_audit(method: str, route: str, status_code: int) -> bool:
    if method not in MUTATING or status_code >= 400 or route in READ_ONLY_POSTS:
        return False
    return route.startswith("/v1/") and not route.startswith(EXEMPT_PREFIXES)


Writer = Callable[[Mutation, UUID | None], Awaitable[None]]


async def write_mutation(mutation: Mutation, request_id: UUID | None) -> None:
    from apps.api.app.db.session import tenant_session

    target_type, target_id = mutation.target()
    async with tenant_session(mutation.tenant_id) as session:
        await session.execute(INSERT, {
            "t": mutation.tenant_id, "u": mutation.user_id, "a": mutation.action,
            "tt": target_type, "tid": target_id, "rid": request_id,
            "m": json.dumps({"route": mutation.route, "status": mutation.status_code}),
        })
        await session.commit()


_writer: list[Writer] = [write_mutation]
_warned: set[str] = set()


def set_writer(writer: Writer | None) -> None:
    """Swap the generic writer (tests capture rows instead of writing them)."""
    _writer[0] = writer or write_mutation


async def request_audit(mutation: Mutation, scope: AuditScope | None) -> bool:
    """Write the generic row unless a named event already covered the request."""
    if scope is not None and scope.named_events:
        return False
    try:
        await _writer[0](mutation, _request_uuid())
    except Exception as exc:  # auditing must never turn a success into a failure
        name = type(exc).__name__
        if name not in _warned:
            _warned.add(name)
            log.warning("audit_write_failed", extra={"error_type": name})
        return False
    return True
