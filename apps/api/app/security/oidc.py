from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.api.app.core.config import Settings
from apps.api.app.security.principal import Principal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ALLOWED_ROLES = frozenset({"student", "editor", "org_admin", "superadmin"})


@dataclass(frozen=True, slots=True)
class OIDCIdentity:
    subject: str


class OIDCVerificationError(ValueError):
    """Raised when an access token does not establish a valid identity."""


class OIDCVerifier:
    """Verify Keycloak-compatible OIDC access tokens without request-time network setup."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._audience = settings.oidc_audience
        self._jwks_url = settings.oidc_jwks_url or (
            f"{self._issuer}/protocol/openid-connect/certs"
        )
        self._client: Any | None = None

    def verify(self, token: str) -> OIDCIdentity:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - packaged installations provide PyJWT
            raise OIDCVerificationError("OIDC verifier is not installed") from exc

        try:
            if self._client is None:
                self._client = jwt.PyJWKClient(self._jwks_url, cache_keys=True)
            signing_key = self._client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except Exception as exc:  # JWT/JWKS errors must not become 500s.
            raise OIDCVerificationError("invalid access token") from exc

        return identity_from_claims(claims)


def identity_from_claims(claims: Mapping[str, Any]) -> OIDCIdentity:
    """Validate the token subject without trusting tenant or role claims."""

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 512:
        raise OIDCVerificationError("missing subject")
    return OIDCIdentity(subject=subject.strip())


async def resolve_current_membership(session: AsyncSession, subject: str) -> Principal:
    """Resolve one current active membership and its authoritative user id."""

    result = await session.execute(
        text("SELECT user_id, tenant_id, role FROM app.resolve_memberships(:subject)"),
        {"subject": subject},
    )
    rows = result.all()
    if len(rows) != 1:
        raise OIDCVerificationError("exactly one active membership required")
    user_value, tenant_value, role = rows[0]
    if not isinstance(role, str) or role not in _ALLOWED_ROLES:
        raise OIDCVerificationError("invalid current membership role")
    try:
        user_id = UUID(str(user_value))
        tenant_id = UUID(str(tenant_value))
    except ValueError as exc:
        raise OIDCVerificationError("invalid current membership identity") from exc
    return Principal(user_id=user_id, tenant_id=tenant_id, role=role)
