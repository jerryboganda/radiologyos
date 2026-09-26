#!/usr/bin/env bash
# Store the owner's Claude subscription token in /opt/radiologyos/app.env
# without echoing it (ADR 0010). The owner creates it with
#   docker exec -it radiologyos-worker-1 claude setup-token
# and pastes it at the hidden prompt. The api/worker pick it up when recreated.
set -euo pipefail

ENV_FILE=/opt/radiologyos/app.env
read -rsp "Paste the token (it stays hidden), then press Enter: " token
echo
token=$(printf '%s' "$token" | tr -d '[:space:]')
case "$token" in
  sk-ant-oat*) ;;
  *) echo "That does not look like a Claude token (it should start with sk-ant-oat). Nothing saved."; exit 1 ;;
esac
[ "${#token}" -ge 80 ] || { echo "The token looks cut off. Nothing saved - please copy it again."; exit 1; }

cp -p "$ENV_FILE" "$ENV_FILE.bak-$(date +%Y%m%d%H%M%S)"
sed -i '/^CLAUDE_CODE_OAUTH_TOKEN=/d' "$ENV_FILE"
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$token" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
unset token
echo "Saved. Tell Claude \"done\"."
