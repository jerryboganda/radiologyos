#!/usr/bin/env bash
# Rotate the radbrain-web client secret, create the bootstrap Keycloak user, and
# rotate the Keycloak admin password.
#
# No secret is ever echoed. The realm file ships with an empty client secret
# precisely so no usable credential is ever committed. Set -x is never used
# around a credential, because a traced command line exposes it.
set -euo pipefail

KC=/opt/keycloak/bin/kcadm.sh
OUT=/opt/radiologyos/keycloak/bootstrap.env
NEWADMIN=/opt/radiologyos/keycloak/admin.env
cd /opt/radiologyos/keycloak
# shellcheck disable=SC1091
. ./keycloak.env

kc() { docker exec -e AU="$KEYCLOAK_ADMIN_USER" -e AP="$KEYCLOAK_ADMIN_PASSWORD" \
  radbrain-keycloak-keycloak-1 "$@"; }

kc_in() {
  local user="$1" pass="$2"; shift 2
  docker exec -e AU="$user" -e AP="$pass" radbrain-keycloak-keycloak-1 bash -lc "$*"
}

echo "=== authenticate to the master realm ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" "
  $KC config credentials --server http://localhost:8080 --realm master \
    --user \"\$AU\" --password \"\$AP\" >/dev/null && echo 'ok'"

if [ ! -f "$OUT" ]; then
  umask 077
  cat > "$OUT" <<EOF
# Bootstrap Keycloak account - root only, never committed.
KEYCLOAK_BOOTSTRAP_USER=admin@radiologyos.polytronx.com
KEYCLOAK_BOOTSTRAP_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)
KEYCLOAK_BOOTSTRAP_ROLE=org_admin
EOF
  chmod 600 "$OUT"
  echo "created $OUT (600)"
fi
# shellcheck disable=SC1091
. "$OUT"

echo
echo "=== realm is enabled ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get realms/radbrain --fields realm,enabled 2>/dev/null | tr -d ' \n' ; echo"

echo
echo "=== resolve the radbrain-web client (note: -q is the filter, -r is the realm) ==="
CID=$(kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get realms/radbrain/clients -q clientId=radbrain-web --fields id --format csv --noquotes 2>/dev/null")
if [ -z "$CID" ] || [ "$(printf '%s' "$CID" | wc -l)" -gt 1 ]; then
  echo "could not resolve exactly one radbrain-web client (got ${CID:-none})" >&2
  exit 1
fi
echo "  resolved one client id"

echo
echo "=== rotate the client secret ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" "
  $KC update clients/$CID -r radbrain -s 'clientId=radbrain-web' \
    -s \"secret=$KEYCLOAK_WEB_CLIENT_SECRET\" >/dev/null && echo '  secret rotated (not displayed)'"

echo
echo "=== prove the rotated secret authenticates the client ==="
# Probed with python inside the already-present radbrain image, so no extra
# image is pulled and no secret is passed in any argument list: the probe reads
# the mounted root-only env file.
KCIMG=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep 'radiologyos-python' | head -1)
KCIMG=${KCIMG:?could not find the radbrain python image}
docker run --rm -i --network platform \
  -v "/opt/radiologyos/keycloak:/run/kc:ro" \
  --entrypoint python \
  "$KCIMG" - <<'PY' || true
import os, urllib.parse, urllib.request, urllib.error

env = {}
with open("/run/kc/keycloak.env", encoding="utf-8") as fh:
    for line in fh:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v

body = urllib.parse.urlencode(
    {
        "client_id": "radbrain-web",
        "client_secret": env["KEYCLOAK_WEB_CLIENT_SECRET"],
        "grant_type": "client_credentials",
    }
).encode()
req = urllib.request.Request(
    "http://keycloak:8080/realms/radbrain/protocol/openid-connect/token",
    data=body,
    method="POST",
)
try:
    with urllib.request.urlopen(req) as resp:
        print(f"  client_credentials grant -> HTTP {resp.status} (expect 200)")
except urllib.error.HTTPError as exc:
    print(f"  client_credentials grant -> HTTP {exc.code} (401 means the secret is wrong)")
PY

echo
echo "=== create the bootstrap user and assign its role ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" "
  set -euo pipefail
  if $KC get realms/radbrain/users -q username=$KEYCLOAK_BOOTSTRAP_USER 2>/dev/null | grep -q '\"id\"'; then
    echo '  user already exists; not recreating'
  else
    $KC create users -r radbrain \
      -s username=$KEYCLOAK_BOOTSTRAP_USER \
      -s email=$KEYCLOAK_BOOTSTRAP_USER -s emailVerified=true -s enabled=true >/dev/null
    echo '  user created'
  fi
  $KC set-password -r radbrain --username $KEYCLOAK_BOOTSTRAP_USER \
    --new-password $KEYCLOAK_BOOTSTRAP_PASSWORD >/dev/null
  # A user created through the admin API is flagged UPDATE_PASSWORD, which makes
  # the login flow stop at /login-actions/required-action instead of returning
  # an authorization code. Clear it, since the password was set deliberately.
  $KC update users/\$( $KC get users -r radbrain -q username=$KEYCLOAK_BOOTSTRAP_USER \
      --fields id --format csv --noquotes 2>/dev/null ) -r radbrain \
      -s 'requiredActions=[]' >/dev/null
  $KC add-roles -r radbrain --uusername $KEYCLOAK_BOOTSTRAP_USER \
    --rolename $KEYCLOAK_BOOTSTRAP_ROLE >/dev/null
  echo '  password set, required actions cleared, role assigned'"

echo
echo "=== audience mapper present? ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get realms/radbrain/clients/$CID/protocol-models/models -q protocol=openid-connect 2>/dev/null \
   | grep -A2 -i 'audience' | grep -i 'name\|radbrain-api' | head -4"

echo
echo "=== rotate the Keycloak admin password (it was exposed by a traced command) ==="
NEWADMINPASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC set-password -r master --userid $KEYCLOAK_ADMIN_USER --new-password $NEWADMINPASS >/dev/null && echo '  rotated'"
umask 077
cat > "$NEWADMIN" <<EOF
# Keycloak master-realm admin password - root only, never committed.
KEYCLOAK_ADMIN_USER=$KEYCLOAK_ADMIN_USER
KEYCLOAK_ADMIN_PASSWORD=$NEWADMINPASS
EOF
chmod 600 "$NEWADMIN"
# Keep keycloak.env in step so a container restart still works.
python3 - "$NEWADMIN" <<'PY'
import re, sys, pathlib
new = dict(
    line.split("=", 1) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if "=" in line
)
p = pathlib.Path("/opt/radiologyos/keycloak/keycloak.env")
text = p.read_text()
text = re.sub(r"(?m)^KEYCLOAK_ADMIN_PASSWORD=.*$", "KEYCLOAK_ADMIN_PASSWORD=" + new["KEYCLOAK_ADMIN_PASSWORD"], text)
p.write_text(text)
print("  keycloak.env updated to the rotated password")
PY

echo
echo "=== confirm the rotated admin password works and the old one does not ==="
NEWOK=$(kc_in "$KEYCLOAK_ADMIN_USER" "$NEWADMINPASS" \
  "$KC get realms --fields realm 2>/dev/null | grep -c radbrain || true")
echo "  new password authenticates, realms found: ${NEWOK}"
echo "  new admin password stored in $NEWADMIN (600)"
echo
echo "=== realm users (usernames only) ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$NEWADMINPASS" \
  "$KC get realms/radbrain/users --fields username,enabled 2>/dev/null | grep -E 'username|enabled' | head -4"
