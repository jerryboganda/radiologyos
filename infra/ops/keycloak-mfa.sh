#!/usr/bin/env bash
# Require an authenticator (TOTP) code for org_admin/superadmin and create the
# radbrain-ops service client used to revoke sessions on account erasure
# (ADR 0032). Idempotent. Run on the VPS as root, only with the owner's OK:
# the owner must be ready to enrol an authenticator at their next sign-in.
#
#   infra/ops/keycloak-mfa.sh           # apply, then report
#   infra/ops/keycloak-mfa.sh --check   # report only
#
# No credential is echoed. The ops client secret is generated once into a
# root-only file and read by the admin script through a read-only mount.
set -euo pipefail

KCDIR=/opt/radiologyos/keycloak
OPS_ENV="$KCDIR/ops-client.env"
HERE=$(cd "$(dirname "$0")" && pwd)

if [ "${1:-}" != "--check" ] && [ ! -f "$OPS_ENV" ]; then
  umask 077
  printf '# radbrain-ops client secret - root only, never committed.\nRADBRAIN_OPS_CLIENT_SECRET=%s\n' \
    "$(openssl rand -base64 36 | tr -d '/+=' | head -c 40)" > "$OPS_ENV"
  chmod 600 "$OPS_ENV"
  echo "created $OPS_ENV (600)"
fi

IMG=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep 'radiologyos-python' | head -1)
IMG=${IMG:?could not find the radbrain python image}
ARGS=(--env /run/kc/keycloak.env /run/kc/admin.env)
if [ "${1:-}" = "--check" ]; then
  ARGS+=(--check)
else
  ARGS+=(--ops-secret-file /run/kc/ops-client.env)
fi

docker run --rm -i --network platform -v "$KCDIR:/run/kc:ro" --entrypoint python \
  "$IMG" - "${ARGS[@]}" < "$HERE/keycloak_mfa.py"
