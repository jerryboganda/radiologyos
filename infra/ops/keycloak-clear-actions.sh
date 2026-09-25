#!/usr/bin/env bash
# Clear the UPDATE_PASSWORD required action on the bootstrap user and set a
# fresh password. Kept separate from the bootstrap script so it can be re-run
# without rotating the client secret or re-creating anything.
set -euo pipefail
KC=/opt/keycloak/bin/kcadm.sh
cd /opt/radiologyos/keycloak
# shellcheck disable=SC1091
. ./keycloak.env
# shellcheck disable=SC1091
. ./bootstrap.env
# shellcheck disable=SC1091
[ -f ./admin.env ] && . ./admin.env

kc_in() {
  local user="$1" pass="$2"; shift 2
  docker exec -e AU="$user" -e AP="$pass" radbrain-keycloak-keycloak-1 bash -lc "$*"
}

echo "=== resolve the bootstrap user id ==="
UID_=$(kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get users -r radbrain -q username=$KEYCLOAK_BOOTSTRAP_USER --fields id --format csv --noquotes 2>/dev/null")
if [ -z "$UID_" ]; then echo "could not resolve the bootstrap user" >&2; exit 1; fi
echo "  resolved"

echo
echo "=== required actions before ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get users/$UID_ -r radbrain --fields requiredActions 2>/dev/null | tr -d ' \n'; echo"

echo
echo "=== clear required actions and reset the password ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" "
  set -euo pipefail
  $KC update users/$UID_ -r radbrain -s 'requiredActions=[]' >/dev/null
  $KC set-password -r radbrain --username $KEYCLOAK_BOOTSTRAP_USER \
    --new-password $KEYCLOAK_BOOTSTRAP_PASSWORD >/dev/null
  echo '  cleared and reset'"

echo
echo "=== required actions after ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get users/$UID_ -r radbrain --fields requiredActions 2>/dev/null | tr -d ' \n'; echo"

echo
echo "=== audience mapper on the web client ==="
CID=$(kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get clients -r radbrain -q clientId=radbrain-web --fields id --format csv --noquotes 2>/dev/null")
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get clients/$CID/protocol-models/models -r radbrain --fields name,protocolMapper 2>/dev/null \
   | tr -d ' \"' | grep -iE 'audience|mapper' | head -5"

echo
echo "=== realm roles ==="
kc_in "$KEYCLOAK_ADMIN_USER" "$KEYCLOAK_ADMIN_PASSWORD" \
  "$KC get roles -r radbrain --fields name 2>/dev/null | tr -d ' \"' | grep -vE '^(name|\[|\]|\{|\})$' | head -8"
