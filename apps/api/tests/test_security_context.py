"""Unit tests for request authentication and tenant-scoping dependencies.

The dependency closures are called directly with stub settings, a stub OIDC
verifier, and a fake membership resolver, so no database or network is used.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import jwt
import pytest
from apps.api.app.core.config import Settings
from apps.api.app.db.session import current_tenant_id
from apps.api.app.security import context
from apps.api.app.security.internal import AUDIENCE, ISSUER, AssertionError_, InternalIdentity
from apps.api.app.security.oidc import OIDCIdentity, OIDCVerificationError
from apps.api.app.security.principal import Principal
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

USER = "10000000-0000-4000-8000-000000000001"
TENANT = "20000000-0000-4000-8000-000000000001"
MEMBER = Principal(UUID("10000000-0000-4000-8000-0000000000aa"),
                   UUID("20000000-0000-4000-8000-0000000000bb"), "editor")
SECRET = "s" * 40
SYSTEM_SESSION = object()


class StubVerifier:
    def __init__(self, error: Exception | None = None,
                 subject: str = "synthetic-subject") -> None:
        self.error, self.subject, self.tokens = error, subject, []

    def verify(self, token: str) -> OIDCIdentity:
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        return OIDCIdentity(subject=self.subject)


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, str]]:
    calls: list[tuple[Any, str]] = []

    async def fake_resolve(session: Any, subject: str) -> Principal:
        calls.append((session, subject))
        if subject == "no-membership":
            raise OIDCVerificationError("exactly one active membership required")
        return MEMBER

    monkeypatch.setattr(context, "resolve_current_membership", fake_resolve)
    return calls


def _dependency(local: bool = True, verifier: StubVerifier | None = None) -> Any:
    settings: Any = SimpleNamespace(is_local_development=local, web_api_secret=SECRET)
    return context.build_principal_from_request(settings, verifier or StubVerifier())  # type: ignore[arg-type]


async def _call(dep: Any, *, scheme: str | None = None, token: str = "tok", user: str = "",
                tenant: str = "", role: str = "", assertion: str = "") -> tuple[Principal, Any]:
    creds = HTTPAuthorizationCredentials(scheme=scheme, credentials=token) if scheme else None
    request = SimpleNamespace(state=SimpleNamespace())
    principal = await dep(creds, request, SYSTEM_SESSION, x_user_id=user, x_tenant_id=tenant,
                          x_role=role, x_radbrain_assertion=assertion)
    return principal, request.state


async def _denied(dep: Any, **kwargs: Any) -> HTTPException:
    with pytest.raises(HTTPException) as denied:
        await _call(dep, **kwargs)
    return denied.value


# ---- local_principal ---------------------------------------------------------


@pytest.mark.parametrize(("user", "tenant"), [(None, TENANT), (USER, None), ("", ""), (USER, "")])
def test_local_principal_absent_headers_give_none(user: str | None, tenant: str | None) -> None:
    assert context.local_principal(user, tenant, "org_admin") is None


def test_local_principal_defaults_to_student_and_accepts_known_roles() -> None:
    assert context.local_principal(USER, TENANT, None) == Principal(UUID(USER), UUID(TENANT))
    empty_role = context.local_principal(USER, TENANT, "")
    assert empty_role is not None and empty_role.role == "student"
    for role in context.ALLOWED_LOCAL_ROLES:
        principal = context.local_principal(USER, TENANT, role)
        assert principal is not None and principal.role == role


@pytest.mark.parametrize(("user", "tenant", "role"), [
    ("not-a-uuid", TENANT, None), (USER, "1234", None), (USER, TENANT, "root"),
    (USER, TENANT, "Superadmin"),
])
def test_local_principal_rejects_malformed_identity(
    user: str, tenant: str, role: str | None
) -> None:
    with pytest.raises(HTTPException) as denied:
        context.local_principal(user, tenant, role)
    assert denied.value.status_code == 400


# ---- bearer tokens -------------------------------------------------------------


@pytest.mark.parametrize("local", [True, False])
async def test_bearer_resolves_membership_and_ignores_identity_headers(
    resolved: list[tuple[Any, str]], local: bool
) -> None:
    verifier = StubVerifier()
    principal, state = await _call(_dependency(local, verifier), scheme="Bearer", token="jwt",
                                   user=USER, tenant=TENANT, role="superadmin")
    assert principal == MEMBER and verifier.tokens == ["jwt"]
    assert resolved == [(SYSTEM_SESSION, "synthetic-subject")]
    assert state.tenant_id == MEMBER.tenant_id and state.requires_tenant_session is True
    assert not hasattr(state, "local_tenant_id")


async def test_non_bearer_scheme_is_refused_before_verification(
    resolved: list[tuple[Any, str]]
) -> None:
    verifier = StubVerifier()
    error = await _denied(_dependency(True, verifier), scheme="Basic", user=USER, tenant=TENANT)
    assert error.status_code == 401 and verifier.tokens == [] and resolved == []


async def test_verifier_error_is_401(resolved: list[tuple[Any, str]]) -> None:
    verifier = StubVerifier(OIDCVerificationError("expired"))
    error = await _denied(_dependency(True, verifier), scheme="bearer")
    assert error.status_code == 401 and error.detail == "invalid access token"
    assert resolved == []


async def test_membership_error_is_401(resolved: list[tuple[Any, str]]) -> None:
    verifier = StubVerifier(subject="no-membership")
    error = await _denied(_dependency(False, verifier), scheme="Bearer")
    assert error.status_code == 401 and resolved == [(SYSTEM_SESSION, "no-membership")]


# ---- web (BFF) assertions ------------------------------------------------------


async def test_web_assertion_resolves_membership(
    resolved: list[tuple[Any, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []

    def fake_verify(token: str, secret: str) -> InternalIdentity:
        seen.append((token, secret))
        return InternalIdentity(subject="web-subject")

    monkeypatch.setattr(context, "verify_internal_assertion", fake_verify)
    principal, state = await _call(_dependency(False), assertion="signed")
    assert principal == MEMBER and seen == [("signed", SECRET)]
    assert resolved == [(SYSTEM_SESSION, "web-subject")]
    assert state.requires_tenant_session is True and state.tenant_id == MEMBER.tenant_id


async def test_bearer_takes_precedence_over_web_assertion(
    resolved: list[tuple[Any, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(token: str, secret: str) -> InternalIdentity:
        raise AssertionError("assertion must not be consulted")

    monkeypatch.setattr(context, "verify_internal_assertion", never)
    principal, _ = await _call(_dependency(False), scheme="Bearer", assertion="signed")
    assert principal == MEMBER


@pytest.mark.parametrize("error", [AssertionError_("bad"), None])
async def test_invalid_web_assertion_or_membership_is_401(
    resolved: list[tuple[Any, str]], monkeypatch: pytest.MonkeyPatch,
    error: Exception | None,
) -> None:
    def fake_verify(token: str, secret: str) -> InternalIdentity:
        if error is not None:
            raise error
        return InternalIdentity(subject="no-membership")

    monkeypatch.setattr(context, "verify_internal_assertion", fake_verify)
    denied = await _denied(_dependency(True), assertion="forged", user=USER, tenant=TENANT)
    assert denied.status_code == 401 and denied.detail == "invalid web assertion"


def _assertion(secret: str, lifetime: int = 60) -> str:
    now = int(time.time())
    claims = {"sub": "web-subject", "iss": ISSUER, "aud": AUDIENCE, "iat": now,
              "exp": now + lifetime}
    return jwt.encode(claims, secret, algorithm="HS256")


async def test_real_web_assertion_is_verified_with_the_configured_secret(
    resolved: list[tuple[Any, str]]
) -> None:
    principal, _ = await _call(_dependency(False), assertion=_assertion(SECRET))
    assert principal == MEMBER
    for forged in (_assertion("x" * 40), _assertion(SECRET, lifetime=3600)):
        assert (await _denied(_dependency(False), assertion=forged)).status_code == 401


# ---- development header identity -------------------------------------------------


async def test_header_identity_is_accepted_in_local_development(
    resolved: list[tuple[Any, str]]
) -> None:
    principal, state = await _call(_dependency(True), user=USER, tenant=TENANT, role="editor")
    assert principal == Principal(UUID(USER), UUID(TENANT), "editor") and resolved == []
    assert state.tenant_id == UUID(TENANT) and state.local_tenant_id == UUID(TENANT)
    assert state.requires_tenant_session is False


async def test_header_identity_is_refused_outside_local_development(
    resolved: list[tuple[Any, str]]
) -> None:
    error = await _denied(_dependency(False), user=USER, tenant=TENANT, role="superadmin")
    assert error.status_code == 401 and error.detail == "OIDC token required"


@pytest.mark.parametrize("env", ["staging", "production", "prod", "preview"])
def test_only_dev_and_test_environments_count_as_local(env: str) -> None:
    assert Settings.model_construct(app_env=env).is_local_development is False
    for local in ("dev", "Development", "TEST"):
        assert Settings.model_construct(app_env=local).is_local_development is True


async def test_missing_identity_is_401_and_malformed_is_400(
    resolved: list[tuple[Any, str]]
) -> None:
    assert (await _denied(_dependency(True))).status_code == 401
    assert (await _denied(_dependency(True), user=USER)).status_code == 401
    assert (await _denied(_dependency(True), user="bad", tenant=TENANT)).status_code == 400


# ---- tenant context and session dependencies ---------------------------------------


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []

    @asynccontextmanager
    async def fake_tenant_session(tenant_id: UUID) -> AsyncIterator[Any]:
        events.append(f"open:{tenant_id}")
        try:
            yield SimpleNamespace(tenant=tenant_id)
        finally:
            events.append(f"close:{tenant_id}")

    monkeypatch.setattr(context, "tenant_session", fake_tenant_session)
    return events


async def test_context_opens_a_tenant_session_for_verified_identity(opened: list[str]) -> None:
    dep = context.build_tenant_context_dependency(lambda: MEMBER)
    request = SimpleNamespace(state=SimpleNamespace(requires_tenant_session=True))
    gen = dep(request, MEMBER)
    assert await anext(gen) is MEMBER
    assert request.state.tenant_session.tenant == MEMBER.tenant_id
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("route failed"))
    assert not hasattr(request.state, "tenant_session")
    assert opened == [f"open:{MEMBER.tenant_id}", f"close:{MEMBER.tenant_id}"]


async def test_context_sets_and_clears_local_tenant_context(opened: list[str]) -> None:
    dep = context.build_tenant_context_dependency(lambda: MEMBER)
    gen = dep(SimpleNamespace(state=SimpleNamespace()), MEMBER)
    assert current_tenant_id() is None
    await anext(gen)
    assert current_tenant_id() == MEMBER.tenant_id and opened == []
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    assert current_tenant_id() is None


async def test_db_session_reuses_the_request_session(opened: list[str]) -> None:
    existing = AsyncSession()
    dep = context.build_tenant_db_session_dependency(lambda: MEMBER)
    gen = dep(SimpleNamespace(state=SimpleNamespace(tenant_session=existing)), MEMBER)
    assert await anext(gen) is existing and opened == []
    with pytest.raises(StopAsyncIteration):
        await anext(gen)


async def test_db_session_opens_one_for_matching_local_tenant(opened: list[str]) -> None:
    dep = context.build_tenant_db_session_dependency(lambda: MEMBER)
    state = SimpleNamespace(local_tenant_id=MEMBER.tenant_id)
    gen = dep(SimpleNamespace(state=state), MEMBER)
    assert (await anext(gen)).tenant == MEMBER.tenant_id
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    assert opened == [f"open:{MEMBER.tenant_id}", f"close:{MEMBER.tenant_id}"]


@pytest.mark.parametrize("state", [
    {}, {"local_tenant_id": UUID(TENANT)}, {"local_tenant_id": str(MEMBER.tenant_id)},
    {"tenant_session": object()},
])
async def test_db_session_fails_closed(opened: list[str], state: dict[str, Any]) -> None:
    dep = context.build_tenant_db_session_dependency(lambda: MEMBER)
    gen = dep(SimpleNamespace(state=SimpleNamespace(**state)), MEMBER)
    with pytest.raises(HTTPException) as denied:
        await anext(gen)
    assert denied.value.status_code == 500 and opened == []
