#!/usr/bin/env bash
# Point the radbrain app at Keycloak and keep the in-memory preview surface off.
# ADR 0011 (personal-first, durable routes) supersedes the ADR 0009 decision to
# enable the preview behind authentication; production runs PREVIEW_ENABLED=false.
#
# The API fetches JWKS over the internal address while validating the issuer.
# That decoupling is what lets the internal issuer work now and the public one
# work after the proxy host exists, without changing verification code.
set -euo pipefail

APPENV=/opt/radiologyos/app.env
KCDIR=/opt/radiologyos/keycloak
# shellcheck disable=SC1091
. "$KCDIR/keycloak.env"

set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$APPENV"; then
    # Values may contain sed metacharacters, so use a python rewrite instead.
    python3 - "$APPENV" "$key" "$value" <<'PY'
import re, sys, pathlib
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
p.write_text(re.sub(rf"(?m)^{key}=.*$", f"{key}={value}", p.read_text()))
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$APPENV"
  fi
}

echo "=== public issuer; JWKS and token exchange stay on the internal address ==="
INTERNAL_ISSUER="http://radbrain-keycloak-keycloak-1:8080/realms/radbrain"
PUBLIC_ISSUER="https://radiologyos.polytronx.com/auth/realms/radbrain"

set_env OIDC_ISSUER "$PUBLIC_ISSUER"
set_env OIDC_JWKS_URL "$INTERNAL_ISSUER/protocol/openid-connect/certs"
set_env OIDC_CLIENT_ID "radbrain-web"
set_env OIDC_AUDIENCE "radbrain-api"
set_env OIDC_CLIENT_SECRET "$KEYCLOAK_WEB_CLIENT_SECRET"
set_env OIDC_INTERNAL_ISSUER "$INTERNAL_ISSUER"

echo "  OIDC_ISSUER=$PUBLIC_ISSUER"
echo "  OIDC_JWKS_URL=$INTERNAL_ISSUER/protocol/openid-connect/certs"
echo "  OIDC_CLIENT_ID=radbrain-web"
echo "  OIDC_AUDIENCE=radbrain-api"
echo "  OIDC_CLIENT_SECRET=<set, not displayed>"

echo
echo "=== keep the in-memory preview surface off (ADR 0011) ==="
set_env PREVIEW_ENABLED "false"
echo "  PREVIEW_ENABLED=false (durable routes only; the preview is outside RLS)"

echo
echo "=== web origin settings ==="
set_env PUBLIC_ORIGIN "https://radiologyos.polytronx.com"
set_env API_PUBLIC_URL "https://radiologyos.polytronx.com"
set_env COOKIE_SECURE "true"

echo
echo "=== cookies must be secure, and the app must be reachable by keycloak ==="
grep -c COOKIE_SECURE "$APPENV" | sed 's/^/  COOKIE_SECURE entries: /'

echo
echo "=== key names now set (values redacted) ==="
sed -E 's/=.*/=<set>/' "$APPENV" | grep -E '^(OIDC|PREVIEW|PUBLIC_ORIGIN|API_PUBLIC_URL|COOKIE_SECURE)' | grep -v '^#'

echo
echo "=== redeploy the app so it picks the configuration up ==="
cd /opt/radiologyos
docker compose --env-file app.env -f platform.yml up -d 2>&1 | tail -6

echo
echo "=== containers ==="
docker compose --env-file app.env -f platform.yml ps -a --format '{{.Name}} | {{.Status}}'
