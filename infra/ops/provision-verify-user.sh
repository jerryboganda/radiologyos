#!/usr/bin/env bash
# Provision the synthetic verification principal used by verify-production-oidc.yml
# (ADR 0032): a Keycloak user with no realm roles (so admin MFA never applies to it)
# and an active *student* membership in its own empty synthetic tenant, so it can
# never see the owner's data. Idempotent; run on the host as root.
#
# Writes /opt/radiologyos/keycloak/verify.env (mode 600) in the same format as
# bootstrap.env, so verify-oidc.py can read it with --bootstrap-file. The password
# is generated here and never printed.
set -euo pipefail

KCDIR=/opt/radiologyos/keycloak
KC=/opt/keycloak/bin/kcadm.sh
KC_CONTAINER=radbrain-keycloak-keycloak-1
VERIFY_ENV="$KCDIR/verify.env"
USERNAME="verify@radbrain.invalid"
cd "$KCDIR"
# shellcheck disable=SC1091
. ./keycloak.env
if [ -f ./admin.env ]; then
  # shellcheck disable=SC1091
  . ./admin.env
fi

if [ -f "$VERIFY_ENV" ]; then
  # shellcheck disable=SC1090
  . "$VERIFY_ENV"
  PASSWORD="$KEYCLOAK_BOOTSTRAP_PASSWORD"
else
  PASSWORD="$(openssl rand -hex 24)"
  (umask 077 && printf 'KEYCLOAK_BOOTSTRAP_USER=%s\nKEYCLOAK_BOOTSTRAP_PASSWORD=%s\nKEYCLOAK_BOOTSTRAP_ROLE=student\n' \
    "$USERNAME" "$PASSWORD" > "$VERIFY_ENV")
fi
chmod 600 "$VERIFY_ENV"

kc() {
  # Credentials travel as container env vars, never on the kcadm command line.
  docker exec -e AU="$KEYCLOAK_ADMIN_USER" -e AP="$KEYCLOAK_ADMIN_PASSWORD" -e VP="$PASSWORD" \
    "$KC_CONTAINER" bash -lc "$KC config credentials --server http://localhost:8080 \
      --realm master --user \"\$AU\" --password \"\$AP\" >/dev/null && $*"
}

echo "=== keycloak user ==="
ID="$(kc "$KC get users -r radbrain -q exact=true -q username=$USERNAME --fields id \
  --format csv --noquotes" | tr -d '\r' | head -1)"
if [ -z "$ID" ]; then
  kc "$KC create users -r radbrain -s username=$USERNAME -s email=$USERNAME \
    -s emailVerified=true -s enabled=true -s firstName=Verification -s lastName=Synthetic" >/dev/null
  ID="$(kc "$KC get users -r radbrain -q exact=true -q username=$USERNAME --fields id \
    --format csv --noquotes" | tr -d '\r' | head -1)"
  echo "  created"
else
  echo "  exists"
fi
kc "$KC set-password -r radbrain --userid $ID --new-password \"\$VP\"" >/dev/null
kc "$KC update users/$ID -r radbrain -s 'requiredActions=[]'" >/dev/null
echo "  password set, no required actions, no realm roles"

echo "=== synthetic tenant and student membership ==="
docker exec -i platform-postgres psql -v ON_ERROR_STOP=1 -U platform_admin -d radiologyos \
  -q -At -v sub="$ID" -v email="$USERNAME" <<'SQL'
WITH existing AS (
  SELECT id FROM users WHERE oidc_subject = :'sub'
), tenant AS (
  INSERT INTO tenants (kind, name)
  SELECT 'personal', 'Verification (synthetic)' WHERE NOT EXISTS (SELECT 1 FROM existing)
  RETURNING id
), app_user AS (
  INSERT INTO users (tenant_id, oidc_subject, email, display_name)
  SELECT id, :'sub', :'email', 'Verification' FROM tenant
  RETURNING tenant_id, id
)
INSERT INTO memberships (tenant_id, user_id, role, active)
SELECT tenant_id, id, 'student', true FROM app_user;
SELECT 'memberships for subject: ' || count(*) FROM app.resolve_memberships(:'sub');
SQL
echo "verify.env ready (mode 600); the password was not printed"
