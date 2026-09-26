"""Shared request-authentication dependencies.

Principal resolution lives here rather than in ``main`` so every router depends
on exactly one implementation. The rule that matters is that it cannot drift
per route:

* a bearer token is verified against the configured issuer, and the subject is
  resolved to a membership row in the database. Tenant and role always come from
  that row, never from a claim;
* header-based identity is honoured **only** outside production, so a preview
  or local header can never become a production authentication path;
* every request runs inside its tenant context, so tenant-scoped queries fail
  closed when the context is missing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.core.config import Settings, get_settings
from apps.api.app.db.session import get_system_session, tenant_context, tenant_session
from apps.api.app.security.internal import AssertionError_, verify_internal_assertion
from apps.api.app.security.oidc import (
    OIDCVerificationError,
    OIDCVerifier,
    resolve_current_membership,
)
from apps.api.app.security.principal import Principal
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

ALLOWED_LOCAL_ROLES = frozenset({"student", "editor", "org_admin", "superadmin"})


def build_bearer_scheme() -> HTTPBearer:
    return HTTPBearer(auto_error=False)


def build_oidc_verifier(settings: Settings) -> OIDCVerifier:
    return OIDCVerifier(settings)


def local_principal(
    x_user_id: str | None,
    x_tenant_id: str | None,
    x_role: str | None,
) -> Principal | None:
    """Build a principal from development headers, or None if absent.

    Malformed values are rejected rather than ignored, so a typo cannot silently
    fall through to an unauthenticated request.
    """
    if not x_user_id or not x_tenant_id:
        return None
    try:
        user_id = UUID(x_user_id)
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid local identity") from exc
    role = x_role or "student"
    if role not in ALLOWED_LOCAL_ROLES:
        raise HTTPException(status_code=400, detail="invalid local role")
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)


def build_principal_from_request(
    settings: Settings,
    oidc_verifier: OIDCVerifier,
) -> Callable[..., Any]:
    """Create the principal dependency bound to a settings instance."""

    async def principal_from_request(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(build_bearer_scheme())
        ],
        request: Request,
        session: Annotated[AsyncSession, Depends(get_system_session)],
        x_user_id: str = Header(default=""),
        x_tenant_id: str = Header(default=""),
        x_role: str = Header(default=""),
        x_radbrain_assertion: str = Header(default=""),
    ) -> Principal:
        """Authenticate OIDC access and resolve current membership from the database.

        A verified token yields a membership row; its tenant and role are
        authoritative and no claim is trusted for either. Outside local
        development a token is the only accepted credential.
        """
        if credentials is not None:
            if credentials.scheme.lower() != "bearer":
                raise HTTPException(status_code=401, detail="bearer token required")
            try:
                identity = oidc_verifier.verify(credentials.credentials)
                principal = await resolve_current_membership(session, identity.subject)
            except OIDCVerificationError as exc:
                raise HTTPException(status_code=401, detail="invalid access token") from exc
            request.state.tenant_id = principal.tenant_id
            request.state.requires_tenant_session = True
            return principal

        if x_radbrain_assertion:
            try:
                internal = verify_internal_assertion(
                    x_radbrain_assertion, settings.web_api_secret
                )
                principal = await resolve_current_membership(session, internal.subject)
            except (AssertionError_, OIDCVerificationError) as exc:
                raise HTTPException(status_code=401, detail="invalid web assertion") from exc
            request.state.tenant_id = principal.tenant_id
            request.state.requires_tenant_session = True
            return principal

        if not settings.is_local_development:
            raise HTTPException(status_code=401, detail="OIDC token required")

        header_principal = local_principal(x_user_id, x_tenant_id, x_role)
        if header_principal is None:
            raise HTTPException(status_code=401, detail="authentication required")
        request.state.tenant_id = header_principal.tenant_id
        request.state.local_tenant_id = header_principal.tenant_id
        request.state.requires_tenant_session = False
        return header_principal

    return principal_from_request


def build_tenant_context_dependency(principal_dependency: Any) -> Callable[..., Any]:
    """Wrap a principal dependency so the request runs inside its tenant context.

    The dependency is bound as a default value rather than an ``Annotated``
    alias. A closure captured inside an ``Annotated[...]`` becomes an
    unresolvable forward reference once annotations are postponed, which Pydantic
    rejects when the schema is built.
    """

    async def principal_context(
        request: Request,
        principal: Principal = Depends(principal_dependency),
    ) -> AsyncIterator[Principal]:
        if getattr(request.state, "requires_tenant_session", False):
            async with tenant_session(principal.tenant_id) as session:
                request.state.tenant_session = session
                try:
                    yield principal
                finally:
                    del request.state.tenant_session
        else:
            with tenant_context(principal.tenant_id):
                yield principal

    return principal_context


def build_tenant_db_session_dependency(principal_dependency: Any) -> Callable[..., Any]:
    """Yield a transaction-local session for OIDC or explicitly local identity.

    Lives here beside the principal dependencies so a request never has a
    session opened by one module and closed by another.
    """

    async def tenant_db_session(
        request: Request,
        principal: Principal = Depends(principal_dependency),
    ) -> AsyncIterator[AsyncSession]:
        session = getattr(request.state, "tenant_session", None)
        if isinstance(session, AsyncSession):
            yield session
            return
        local_tenant_id = getattr(request.state, "local_tenant_id", None)
        if isinstance(local_tenant_id, UUID) and local_tenant_id == principal.tenant_id:
            async with tenant_session(principal.tenant_id) as local_session:
                yield local_session
            return
        raise HTTPException(status_code=500, detail="tenant session unavailable")

    return tenant_db_session


def build_shared_dependencies() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Return ``(principal_from_request, principal_context)`` for this app instance.

    Built from a single settings and verifier instance so the whole process
    agrees on the issuer, the audience, and whether headers are acceptable.
    """
    settings = get_settings()
    verifier = build_oidc_verifier(settings)
    principal_dependency = build_principal_from_request(settings, verifier)
    return principal_dependency, build_tenant_context_dependency(principal_dependency)


__all__ = [
    "ALLOWED_LOCAL_ROLES",
    "build_principal_from_request",
    "build_shared_dependencies",
    "build_tenant_context_dependency",
    "build_tenant_db_session_dependency",
    "local_principal",
]
