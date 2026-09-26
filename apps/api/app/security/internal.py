"""Backend-for-frontend assertions from the web server to the API.

The SvelteKit server holds the user's session and calls the API on their
behalf. It signs a short-lived HS256 assertion carrying only the OIDC subject,
with a secret shared by the web and API containers (never the browser). The API
verifies it and resolves tenant and role from the membership table, exactly as
for an OIDC token, so no claim is trusted for authorization.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

ISSUER = "radbrain-web"
AUDIENCE = "radbrain-api-internal"
MAX_LIFETIME_S = 120
MIN_SECRET_LENGTH = 32


class AssertionError_(Exception):  # noqa: N801 - avoid shadowing builtin AssertionError
    """The internal assertion is missing, malformed, or not trusted."""


@dataclass(frozen=True, slots=True)
class InternalIdentity:
    subject: str


def verify_internal_assertion(token: str, secret: str) -> InternalIdentity:
    if len(secret) < MIN_SECRET_LENGTH:
        raise AssertionError_("internal assertions are not configured")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise AssertionError_("invalid internal assertion") from exc
    if int(claims["exp"]) - int(claims["iat"]) > MAX_LIFETIME_S:
        raise AssertionError_("internal assertion lifetime too long")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AssertionError_("internal assertion has no subject")
    return InternalIdentity(subject=subject)
