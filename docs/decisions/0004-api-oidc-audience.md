# ADR 0004: Separate the OIDC API audience from the web client

Status: **Accepted for M0; staging provider configuration remains required**
Date: 2026-09-24
Decision owners: engineering and security reviewers
Scope: API bearer-token validation and local Keycloak realm

## Context

The SvelteKit web client uses OIDC authorization-code flow with PKCE and receives an
access token for API calls. The API must validate that token as a token intended for
its own resource server. Reusing the web client identifier as the API audience couples
resource-server authorization to the browser client and can accept a token minted for
the wrong service. Tenant and role claims are not trusted; the API resolves membership
from PostgreSQL after token verification.

## Decision

Configure the API with a separate `OIDC_AUDIENCE` (local default `radbrain-api`) and
require that audience during JWT verification. Keep `OIDC_CLIENT_ID` for the web
client's ID-token audience and token exchange. The local Keycloak realm maps
`radbrain-api` into access tokens only; the web session flow continues to verify the
ID token against `radbrain-web`.

The API must receive the same audience value through deployment configuration, and
staging must use a reviewed provider audience. A token with a valid signature but a
missing or mismatched API audience is rejected before membership lookup.

## Consequences

- Access tokens minted for the web client alone cannot authorize API requests.
- Staging deployments must configure both the provider audience mapper and
  `OIDC_AUDIENCE`; a missing mapper is a fail-closed staging error, not a reason to
  disable audience validation.
- The web client must not receive the API's provider secret or treat its client ID as
  the API resource-server identity.
- Keycloak realm fixtures are local development configuration only and are not a
  production identity or secret-management decision.

## Rejected alternatives

- **Use `OIDC_CLIENT_ID` as the API audience:** simpler configuration, but it makes a
  browser-facing client identifier the API resource-server trust boundary.
- **Trust tenant or role claims:** allows stale or forged membership data to bypass the
  authoritative database membership check.
- **Disable audience validation for local convenience:** weakens the API boundary and
  makes staging behavior differ from the tested contract.

## Verification

The API regression test covers a valid `radbrain-api` audience and rejects a validly
signed token for `radbrain-web`. M0 production verification must additionally capture a
real browser login, callback, invalid-token denial, wrong-audience denial,
unauthorized tenant switch, role denial, and logout without recording token values.
