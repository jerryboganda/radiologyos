#!/usr/bin/env bash
# Store the owner's Mistral API key (free Experiment plan, ADR 0022) in
# /opt/radiologyos/app.env without echoing it, after checking it with Mistral.
set -euo pipefail

ENV_FILE=/opt/radiologyos/app.env
read -rsp "Paste the Mistral API key (it stays hidden), then press Enter: " key
echo
key=$(printf '%s' "$key" | tr -d '[:space:]')
[ "${#key}" -ge 20 ] || { echo "That key looks too short. Nothing saved - please copy it again."; exit 1; }

status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
  -H "Authorization: Bearer $key" https://api.mistral.ai/v1/models || true)
if [ "$status" != "200" ]; then
  echo "Mistral did not accept this key (HTTP $status). Nothing saved."
  echo "Check you copied the whole key, and that the Experiment plan is active."
  exit 1
fi

cp -p "$ENV_FILE" "$ENV_FILE.bak-$(date +%Y%m%d%H%M%S)"
sed -i '/^MISTRAL_API_KEY=/d' "$ENV_FILE"
printf 'MISTRAL_API_KEY=%s\n' "$key" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
unset key
echo "Saved, and Mistral confirmed the key works. Tell Claude \"done\"."
