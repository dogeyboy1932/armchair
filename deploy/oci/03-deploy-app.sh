#!/usr/bin/env bash
# SSH into the VM created by 02-create-vm.sh and run the SIIP installer.
# Reads state from deploy/oci/state/vm.env.
#
# Optional env vars:
#   GEMINI_API_KEY  - if set, baked into the .env on the server so LLM scripts run
#   SIIP_DOMAIN     - if set, configures Caddy with HTTPS for this domain
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/oci"
STATE="$ROOT/state"

if [[ ! -f "$STATE/vm.env" ]]; then
  echo "Missing $STATE/vm.env — run 02-create-vm.sh first." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$STATE/vm.env"

SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$STATE/known_hosts" -o ConnectTimeout=10)

echo "==> Waiting for SSH on $PUBLIC_IP (cloud-init can take 30-90s)…"
for i in $(seq 1 30); do
  if ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$SSH_USER@$PUBLIC_IP" 'echo ok' >/dev/null 2>&1; then
    echo "==> SSH ready."
    break
  fi
  printf '.'
  sleep 5
done
echo ""

echo "==> Running SIIP installer on the VM (this takes 20-40 min)…"
ENV_PREFIX=""
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  ENV_PREFIX="GEMINI_API_KEY='${GEMINI_API_KEY}' "
fi
if [[ -n "${SIIP_DOMAIN:-}" ]]; then
  ENV_PREFIX="${ENV_PREFIX}SIIP_DOMAIN='${SIIP_DOMAIN}' "
fi

# Stream installer output live
ssh "${SSH_OPTS[@]}" "$SSH_USER@$PUBLIC_IP" \
  "${ENV_PREFIX}curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/oracle-install.sh | bash"

echo ""
echo "==> Verifying health endpoint…"
sleep 5
if curl -sf "http://$PUBLIC_IP:8080/health" >/dev/null; then
  echo "✓ Health check passed."
else
  echo "Health check failed — check logs on the server:"
  echo "  ssh -i $SSH_KEY ubuntu@$PUBLIC_IP"
  echo "  cd ~/armchair && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend"
  exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════"
if [[ -n "${SIIP_DOMAIN:-}" ]]; then
  echo "  ✓ SIIP is live at: https://${SIIP_DOMAIN}"
else
  echo "  ✓ SIIP is live at: http://${PUBLIC_IP}:8080"
fi
echo "════════════════════════════════════════════════════════════"
echo ""
echo "SSH access:  ssh -i $SSH_KEY ubuntu@$PUBLIC_IP"
echo "API docs:    http://${PUBLIC_IP}:8080/docs"
echo "Upload UI:   http://${PUBLIC_IP}:8080/upload"
