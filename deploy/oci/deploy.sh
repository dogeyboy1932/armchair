#!/usr/bin/env bash
# All-in-one orchestrator: installs OCI CLI, configures it, creates the VM, deploys the app.
#
# Required env vars (or paste into deploy/oci/credentials.env beforehand):
#   OCI_TENANCY        ocid1.tenancy.oc1..…
#   OCI_USER           ocid1.user.oc1..…
#   OCI_FINGERPRINT    12:34:…
#   OCI_REGION         e.g. us-chicago-1
#   OCI_KEY_FILE       absolute path to the downloaded .pem
#
# Optional:
#   GEMINI_API_KEY     bakes a Gemini key into the server's .env
#   SIIP_DOMAIN        if you want HTTPS via Caddy on a domain you own
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/oci"

# Source credentials from file if present (so secrets aren't in shell history)
if [[ -f "$ROOT/credentials.env" ]]; then
  echo "==> Loading credentials from $ROOT/credentials.env"
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/credentials.env"
  set +a
fi

bash "$ROOT/00-install-cli.sh"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

bash "$ROOT/01-configure.sh"
bash "$ROOT/02-create-vm.sh"
bash "$ROOT/03-deploy-app.sh"
