from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from apps.api.app.core.config import Settings
from apps.api.app.security.oidc import (
    OIDCVerificationError,
    OIDCVerifier,
    identity_from_claims,
    resolve_current_membership,
)
from cryptography.hazmat.primitives.asymmetric import rsa


class _MembershipSession:
    def __init__(self, rows: list[tuple[UUID, UUID, str]]) -> None:
        self._rows = rows

    async def execute(self, statement, parameters):  # type: ignore[no-untyped-def]
        assert parameters["subject"] == "keycloak|preview-user"
        return SimpleNamespace(all=lambda: self._rows)


@pytest.mark.asyncio
async def test_current_database_membership_supplies_authoritative_user_tenant_and_role() -> None:
    subject = "keycloak|preview-user"
    user_id = UUID("10000000-0000-0000-0000-000000000001")
    tenant_id = UUID("20000000-0000-0000-0000-000000000002")
    principal = await resolve_current_membership(
        _MembershipSession([(user_id, tenant_id, "org_admin")]), subject
    )
    assert principal.user_id == user_id
    assert principal.tenant_id == tenant_id
    assert principal.role == "org_admin"


@pytest.mark.asyncio
async def test_ambiguous_current_membership_is_rejected() -> None:
    subject = "keycloak|preview-user"
    user_id = UUID("10000000-0000-0000-0000-000000000001")
    with pytest.raises(OIDCVerificationError, match="exactly one"):
        await resolve_current_membership(
            _MembershipSession(
                [
                    (user_id, UUID("20000000-0000-0000-0000-000000000002"), "student"),
                    (user_id, UUID("30000000-0000-0000-0000-000000000003"), "student"),
                ]
            ),
            subject,
        )


def test_oidc_identity_ignores_tenant_and_role_claims() -> None:
    identity = identity_from_claims(
        {
            "sub": "keycloak|preview-user",
            "memberships": [
                {
                    "tenant_id": "20000000-0000-0000-0000-000000000002",
                    "role": "superadmin",
                    "active": False,
                }
            ],
        }
    )
    assert identity.subject == "keycloak|preview-user"


def test_oidc_verifier_requires_configured_api_audience(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": "https://id.example/realms/radbrain",
            "aud": "radbrain-api",
            "sub": "10000000-0000-0000-0000-000000000001",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    class _SigningKey:
        key = private_key.public_key()

    class _JWKClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_signing_key_from_jwt(self, _token: str) -> _SigningKey:
            return _SigningKey()

    monkeypatch.setattr(jwt, "PyJWKClient", _JWKClient)
    verifier = OIDCVerifier(
        Settings(
            oidc_issuer="https://id.example/realms/radbrain",
            oidc_client_id="radbrain-api",
        )
    )

    assert verifier.verify(token).subject == "10000000-0000-0000-0000-000000000001"

    wrong_audience_token = jwt.encode(
        {
            "iss": "https://id.example/realms/radbrain",
            "aud": "radbrain-web",
            "sub": "10000000-0000-0000-0000-000000000001",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    with pytest.raises(OIDCVerificationError, match="invalid access token"):
        verifier.verify(wrong_audience_token)


def test_oidc_identity_rejects_empty_subject() -> None:
    with pytest.raises(OIDCVerificationError, match="missing subject"):
        identity_from_claims({"sub": "   "})


def test_oidc_identity_accepts_non_uuid_subject() -> None:
    assert identity_from_claims({"sub": "provider|subject"}).subject == "provider|subject"
