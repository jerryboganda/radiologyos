"""Revoke an erased user's identity-provider sessions (ADR 0032, G35).

Best effort, behind configuration: with ``KEYCLOAK_ADMIN_URL``,
``KEYCLOAK_ADMIN_CLIENT_ID`` and ``KEYCLOAK_ADMIN_CLIENT_SECRET`` set (the
``radbrain-ops`` service client, which holds only ``manage-users``), the
account-erasure job logs the user out of every Keycloak session before their
identity row is erased. The outcome is a fixed word recorded on the job; a
failure never blocks the erasure, because the API already refuses the erased
user (no membership) and Keycloak sessions expire on their own (10 h maximum).
"""

from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import quote

import httpx

log = logging.getLogger("radbrain.datarights")
Outcome = Literal["revoked", "not_found", "not_configured", "no_subject", "failed"]


async def revoke_sessions(
    subject: str | None, base_url: str, realm: str, client_id: str, client_secret: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Outcome:
    """Log ``subject`` (the Keycloak user id) out of all sessions."""
    if not subject:
        return "no_subject"
    if not (base_url and client_id and client_secret):
        return "not_configured"
    base = base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            token = await client.post(
                f"{base}/realms/{quote(realm, safe='')}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": client_id,
                      "client_secret": client_secret})
            token.raise_for_status()
            access = str(token.json()["access_token"])
            response = await client.post(
                f"{base}/admin/realms/{quote(realm, safe='')}/users/"
                f"{quote(subject, safe='')}/logout",
                headers={"Authorization": f"Bearer {access}"})
        if response.status_code == 404:
            return "not_found"
        response.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("idp_revocation_failed error=%s", type(exc).__name__)
        return "failed"
    return "revoked"
