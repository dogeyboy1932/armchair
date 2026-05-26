#!/usr/bin/env bash
# Write ~/.oci/config and copy the user's API private key into place.
# Reads credentials from environment variables (set by the orchestrator or by you).
#
# Required env vars:
#   OCI_TENANCY        - tenancy OCID (ocid1.tenancy.oc1..…)
#   OCI_USER           - user OCID    (ocid1.user.oc1..…)
#   OCI_FINGERPRINT    - API key fingerprint (e.g. 12:34:56:…)
#   OCI_REGION         - region key   (e.g. us-chicago-1)
#   OCI_KEY_FILE       - absolute path to the downloaded private key .pem
set -euo pipefail

: "${OCI_TENANCY:?set OCI_TENANCY}"
: "${OCI_USER:?set OCI_USER}"
: "${OCI_FINGERPRINT:?set OCI_FINGERPRINT}"
: "${OCI_REGION:?set OCI_REGION}"
: "${OCI_KEY_FILE:?set OCI_KEY_FILE (absolute path to your downloaded private key .pem)}"

if [[ ! -f "$OCI_KEY_FILE" ]]; then
  echo "Private key file not found at: $OCI_KEY_FILE" >&2
  exit 1
fi

mkdir -p "$HOME/.oci"
chmod 700 "$HOME/.oci"

DEST_KEY="$HOME/.oci/oci_api_key.pem"
cp "$OCI_KEY_FILE" "$DEST_KEY"
chmod 600 "$DEST_KEY"

cat > "$HOME/.oci/config" <<EOF
[DEFAULT]
user=$OCI_USER
fingerprint=$OCI_FINGERPRINT
tenancy=$OCI_TENANCY
region=$OCI_REGION
key_file=$DEST_KEY
EOF
chmod 600 "$HOME/.oci/config"

echo "==> Wrote ~/.oci/config and installed key at $DEST_KEY"

# Smoke test against the API
if command -v oci >/dev/null 2>&1; then
  echo "==> Verifying credentials with: oci iam region list"
  oci iam region list --output table | head -20
  echo "==> Credentials work."
else
  echo "WARN: oci CLI not on PATH. Activate the venv first: source deploy/oci/.venv/bin/activate"
fi
