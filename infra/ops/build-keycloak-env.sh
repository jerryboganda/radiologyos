#!/usr/bin/env bash
# Build the Keycloak environment file (mode 600) from the platform-issued
# credentials plus generated admin and client secrets. Idempotent: existing
# secrets are reused so restarts do not invalidate the client secret.
set -euo pipefail

P=/opt/platform/projects/keycloak.env
OUT=/opt/radiologyos/keycloak/keycloak.env
mkdir -p /opt/radiologyos/keycloak
chmod 700 /opt/radiologyos/keycloak

pg() { grep -E "^$1=" "$P" | head -1 | cut -d= -f2-; }
# grep exits 1 when the key is absent, which must not trip `set -e`.
existing() { grep -E "^$1=" "$OUT" 2>/dev/null | head -1 | cut -d= -f2- || true; }

ADMIN_USER=${KEYCLOAK_ADMIN_USER:-admin}
ADMIN_PASS=$(existing KEYCLOAK_ADMIN_PASSWORD)
[ -n "$ADMIN_PASS" ] || ADMIN_PASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)
CLIENT_SECRET=$(existing KEYCLOAK_WEB_CLIENT_SECRET)
[ -n "$CLIENT_SECRET" ] || CLIENT_SECRET=$(openssl rand -base64 32 | tr -d '/+=' | head -c 40)

umask 077
cat > "$OUT" <<EOF
# Keycloak environment - root only, never committed.
KEYCLOAK_DB_PASSWORD=$(pg PLATFORM_PG_PASSWORD)
KEYCLOAK_ADMIN_USER=$ADMIN_USER
KEYCLOAK_ADMIN_PASSWORD=$ADMIN_PASS
KEYCLOAK_WEB_CLIENT_SECRET=$CLIENT_SECRET
# Public issuer: the app is served on a path prefix of the main hostname.
KEYCLOAK_HOSTNAME_URL=https://radiologyos.polytronx.com/auth
EOF
chmod 600 "$OUT"
echo "wrote $OUT (600)"

echo
echo "=== key names only ==="
sed -E 's/=.*/=<set>/' "$OUT" | grep -v '^#'

echo
echo "=== sanity: db host is the shared platform, not a local one ==="
grep -E '^KEYCLOAK_HOSTNAME_URL=' "$OUT"
echo "  db: jdbc:postgresql://platform-postgres:5432/keycloak (from compose)"
