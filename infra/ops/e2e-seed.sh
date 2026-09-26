#!/usr/bin/env bash
# Seed the disposable CI Compose stack for the browser E2E job (.github/workflows/e2e.yml).
#
# 1. Sets the radbrain-web client secret in Keycloak to the web container's value
#    (the realm file ships an empty secret on purpose).
# 2. Creates one synthetic Keycloak user with the caller's random password.
# 3. Inserts a synthetic personal tenant, a user keyed to the Keycloak subject,
#    and an active student membership, as the bootstrap database superuser
#    (RLS on tenants admits no other role to create a tenant).
#
# Required env: E2E_USERNAME, E2E_PASSWORD. Credentials never appear in argv or
# output: curl reads them from stdin or a 0600 header file, jq from the
# environment. Only the (non-secret) subject is printed, and appended to
# $GITHUB_ENV as RADBRAIN_E2E_EXPECTED_SUBJECT when that file is set.
# For disposable local/CI stacks only; never point this at production.
set -euo pipefail

: "${E2E_USERNAME:?E2E_USERNAME is required}"
: "${E2E_PASSWORD:?E2E_PASSWORD is required}"
KC_URL="${KC_URL:-http://localhost:8080}"
REALM="${KC_REALM:-radbrain}"
export KC_ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
export KC_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-change-me}"
export E2E_EMAIL="${E2E_USERNAME}@example.test"
PG_USER="${POSTGRES_USER:-radbrain_bootstrap}"
PG_DB="${POSTGRES_DB:-radbrain}"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
chmod 700 "$workdir"
auth_header="$workdir/auth-header"

admin_login() {
  local token
  token="$(jq -rn '"client_id=admin-cli&grant_type=password&username=\(env.KC_ADMIN_USER|@uri)&password=\(env.KC_ADMIN_PASSWORD|@uri)"' \
    | curl -fsS -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
        -H 'content-type: application/x-www-form-urlencoded' --data-binary @- \
    | jq -r '.access_token // empty')"
  if [ -z "$token" ]; then
    echo "Keycloak admin login failed" >&2
    exit 1
  fi
  (umask 077 && printf 'Authorization: Bearer %s\n' "$token" > "$auth_header")
}

kc() {
  # kc METHOD PATH [curl args...]; the bearer token is read from the header file.
  local method="$1" path="$2"
  shift 2
  curl -fsS -X "$method" "$KC_URL/admin/realms/$REALM$path" -H @"$auth_header" "$@"
}

set_client_secret() {
  local client_id
  client_id="$(kc GET '/clients?clientId=radbrain-web' | jq -r '.[0].id // empty')"
  if [ -z "$client_id" ]; then
    echo "radbrain-web client not found in realm $REALM" >&2
    exit 1
  fi
  WEB_CLIENT_SECRET="$(docker compose exec -T web printenv OIDC_CLIENT_SECRET)"
  export WEB_CLIENT_SECRET
  if [ -z "$WEB_CLIENT_SECRET" ]; then
    echo "the web container has no OIDC_CLIENT_SECRET" >&2
    exit 1
  fi
  kc GET "/clients/$client_id" | jq '.secret = env.WEB_CLIENT_SECRET' \
    | kc PUT "/clients/$client_id" -H 'content-type: application/json' --data-binary @- >/dev/null
  echo "radbrain-web client secret set (value not displayed)"
}

create_user() {
  jq -n '{
      username: env.E2E_USERNAME, email: env.E2E_EMAIL, emailVerified: true, enabled: true,
      firstName: "E2E", lastName: "Student", requiredActions: [],
      credentials: [{type: "password", value: env.E2E_PASSWORD, temporary: false}]
    }' \
    | kc POST /users -H 'content-type: application/json' --data-binary @- >/dev/null
  SUBJECT="$(kc GET "/users?exact=true&username=$(jq -rn 'env.E2E_USERNAME|@uri')" | jq -r '.[0].id // empty')"
  if [ -z "$SUBJECT" ]; then
    echo "the synthetic user was not created" >&2
    exit 1
  fi
  echo "synthetic Keycloak user created"
}

provision_membership() {
  local resolved
  resolved="$(insert_membership)"
  if [ "$resolved" != "1" ]; then
    echo "expected exactly one resolvable membership, got: ${resolved:-none}" >&2
    exit 1
  fi
  echo "synthetic tenant, user, and student membership provisioned"
}

insert_membership() {
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -q -At -U "$PG_USER" -d "$PG_DB" \
    -v sub="$SUBJECT" -v email="$E2E_EMAIL" <<'SQL'
WITH tenant AS (
  INSERT INTO tenants (kind, name) VALUES ('personal', 'E2E synthetic tenant') RETURNING id
), app_user AS (
  INSERT INTO users (tenant_id, oidc_subject, email, display_name)
  SELECT id, :'sub', :'email', 'E2E Student' FROM tenant
  RETURNING tenant_id, id
)
INSERT INTO memberships (tenant_id, user_id, role, active)
SELECT tenant_id, id, 'student', true FROM app_user;

SELECT count(*) FROM app.resolve_memberships(:'sub');
SQL
}

admin_login
set_client_secret
create_user
provision_membership
echo "subject: $SUBJECT"
if [ -n "${GITHUB_ENV:-}" ]; then
  echo "RADBRAIN_E2E_EXPECTED_SUBJECT=$SUBJECT" >> "$GITHUB_ENV"
fi
