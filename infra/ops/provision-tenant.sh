#!/usr/bin/env bash
# Provision the bootstrap organisation in radbrain's own database, keyed to the
# Keycloak subject, and rotate the Keycloak master-realm admin password.
#
# The subject is the join between identity and data. It is written to a
# root-only file and is never printed in full.
set -euo pipefail

KC=/opt/keycloak/bin/kcadm.sh
KCDIR=/opt/radiologyos/keycloak
cd "$KCDIR"
# shellcheck disable=SC1091
. ./keycloak.env
# shellcheck disable=SC1091
. ./bootstrap.env

ADMINFILE="$KCDIR/admin.env"

kc_in() {
  local user="$1" pass="$2"; shift 2
  docker exec -e AU="$user" -e AP="$pass" radbrain-keycloak-keycloak-1 bash -lc "$*"
}

AUTH_USER="$KEYCLOAK_ADMIN_USER"
AUTH_PASS="$KEYCLOAK_ADMIN_PASSWORD"
if [ -f "$ADMINFILE" ]; then
  # shellcheck disable=SC1091
  . "$ADMINFILE"
  AUTH_PASS="$KEYCLOAK_ADMIN_PASSWORD"
fi

echo "=== rotate the Keycloak master admin password (needs the user id, not the name) ==="
NEWADMINPASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)
MASTERID=$(kc_in "$AUTH_USER" "$AUTH_PASS" \
  "$KC get users -r master -q username=$KEYCLOAK_ADMIN_USER --fields id --format csv --noquotes 2>/dev/null")
if [ -z "$MASTERID" ]; then
  echo "could not resolve the master admin user id" >&2
  exit 1
fi
echo "  master admin id resolved"
kc_in "$AUTH_USER" "$AUTH_PASS" \
  "$KC set-password -r master --userid $MASTERID --new-password $NEWADMINPASS >/dev/null && echo '  rotated'"
umask 077
cat > "$ADMINFILE" <<EOF
# Keycloak master-realm admin password - root only, never committed.
KEYCLOAK_ADMIN_USER=$KEYCLOAK_ADMIN_USER
KEYCLOAK_ADMIN_PASSWORD=$NEWADMINPASS
EOF
chmod 600 "$ADMINFILE"
python3 - "$ADMINFILE" <<'PY'
import re, sys, pathlib
new = dict(
    line.split("=", 1) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if "=" in line
)
p = pathlib.Path("/opt/radiologyos/keycloak/keycloak.env")
t = p.read_text()
t = re.sub(r"(?m)^KEYCLOAK_ADMIN_PASSWORD=.*$", "KEYCLOAK_ADMIN_PASSWORD=" + new["KEYCLOAK_ADMIN_PASSWORD"], t)
p.write_text(t)
print("  keycloak.env updated so a container restart still works")
PY
AUTH_PASS="$NEWADMINPASS"

echo
echo "=== audience mapper present? ==="
CID=$(kc_in "$AUTH_USER" "$AUTH_PASS" \
  "$KC get realms/radbrain/clients -q clientId=radbrain-web --fields id --format csv --noquotes 2>/dev/null")
kc_in "$AUTH_USER" "$AUTH_PASS" \
  "$KC get realms/radbrain/clients/$CID/protocol-models/models --fields name,protocolMapper 2>/dev/null \
   | tr -d ' \"' | grep -iE 'audience' | head -3"

echo
echo "=== the Keycloak user id (this is the oidc_subject) ==="
SUBJECT=$(kc_in "$AUTH_USER" "$AUTH_PASS" \
  "$KC get realms/radbrain/users -q username=$KEYCLOAK_BOOTSTRAP_USER --fields id --format csv --noquotes 2>/dev/null")
if [ -z "$SUBJECT" ]; then echo "could not resolve the bootstrap user id" >&2; exit 1; fi
echo "  resolved (value withheld; written to root-only file)"

umask 077
echo "KEYCLOAK_BOOTSTRAP_SUBJECT=$SUBJECT" > "$KCDIR/subject.env"
chmod 600 "$KCDIR/subject.env"

echo
echo "=== provision the organisation, user, and membership in radbrain's database ==="
# Tenant, user and membership bootstrap runs as the platform superuser, NOT the
# migrator and NOT the app role. RLS on tenants deliberately applies to every
# non-superuser role, so this is the only role permitted to create a tenant -
# which is the correct boundary: tenant creation is an administrative act, not a
# migration one.
PLATFORM_ADMIN_PASS=$(grep -E '^PLATFORM_PG_SUPERPASS=' /opt/platform/env.local | cut -d= -f2-)
APPPASS=$(grep -E '^RADBRAIN_APP_PASSWORD=' /opt/radiologyos/secrets.env | cut -d= -f2-)
MIGPASS=$(grep -E '^RADBRAIN_MIGRATOR_PASSWORD=' /opt/radiologyos/secrets.env | cut -d= -f2-)

docker exec -i platform-postgres \
  psql -v ON_ERROR_STOP=1 -U platform_admin -d radiologyos -q \
      -v sub="$SUBJECT" -v email="$KEYCLOAK_BOOTSTRAP_USER" <<'SQL'
-- Values arrive via psql -v flags, not the environment: psql does not expose
-- environment variables as variables, so \set x :'ENV' would store the literal
-- text ":'ENV'" as the value.
-- Clean up any row written by an earlier run that passed psql variables
-- incorrectly. Memberships first: a membership references its user, so the
-- reverse order violates the foreign key.
DELETE FROM memberships
WHERE user_id IN (SELECT id FROM users WHERE oidc_subject LIKE ':%');
DELETE FROM users WHERE oidc_subject LIKE ':%';

INSERT INTO tenants (id, kind, name, plan)
VALUES ('40000000-0000-0000-0000-000000000001', 'organization', 'RadiologyOS', 'unconfigured')
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (tenant_id, oidc_subject, email, display_name)
VALUES ('40000000-0000-0000-0000-000000000001', :'sub', :'email', 'Bootstrap administrator')
ON CONFLICT (tenant_id, oidc_subject) DO NOTHING;

INSERT INTO memberships (tenant_id, user_id, role, active)
SELECT '40000000-0000-0000-0000-000000000001', u.id, 'org_admin', true
FROM users u
WHERE u.tenant_id = '40000000-0000-0000-0000-000000000001'
  AND u.oidc_subject = :'sub'
ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = 'org_admin', active = true;
SQL

echo
echo "=== verify the membership resolves the way the API will ==="
docker exec -e PGPASSWORD="$MIGPASS" platform-postgres \
  psql -U radbrain_migrator -d radiologyos -Atc \
  "select 'rows returned by app.resolve_memberships: '||count(*)
     from app.resolve_memberships('$SUBJECT');"

echo
echo "=== tenant row, read as the platform admin (RLS hides tenants from other roles) ==="
docker exec -e PGPASSWORD="$PLATFORM_ADMIN_PASS" platform-postgres \
  psql -U platform_admin -d radiologyos -Atc \
  "select 'tenant '||id||' kind='||kind||' plan='||plan from tenants where id='40000000-0000-0000-0000-000000000001';"
echo "  (the migrator sees zero tenants by design; RLS on tenants applies to every non-superuser)"

echo
echo "=== the app role cannot see or reach another tenant through RLS ==="
docker exec -e PGPASSWORD="$APPPASS" platform-postgres \
  psql -U radbrain_app -d radiologyos -Atc \
  "select 'rows visible to app role with no tenant context: '||count(*) from tenants;" 2>&1 | tail -1
echo
echo "subject stored in $KCDIR/subject.env (600); admin password in $ADMINFILE (600)"
