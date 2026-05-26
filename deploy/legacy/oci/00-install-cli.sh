#!/usr/bin/env bash
# Install the Oracle Cloud CLI into a local Python venv (no sudo, no system pollution).
# Idempotent: re-running is safe.
#
# After running this, `source deploy/oci/.venv/bin/activate` to get the `oci` command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/oci"
VENV="$ROOT/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found. Install python3 first." >&2
  exit 1
fi

if [[ ! -d "$VENV" ]]; then
  echo "==> Creating Python venv at $VENV"
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

pip install --quiet --upgrade pip
pip install --quiet "oci-cli>=3.0"

echo "==> OCI CLI installed: $(oci --version)"
echo "Activate with: source $VENV/bin/activate"
