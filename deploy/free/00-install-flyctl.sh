#!/usr/bin/env bash
# Install the Fly.io CLI locally if not already present.
set -euo pipefail

if command -v flyctl >/dev/null 2>&1; then
  echo "==> flyctl already installed: $(flyctl version)"
  exit 0
fi

echo "==> Installing flyctl…"
# Official installer drops binary in ~/.fly/bin
curl -L https://fly.io/install.sh | sh

export FLYCTL_INSTALL="${FLYCTL_INSTALL:-$HOME/.fly}"
export PATH="$FLYCTL_INSTALL/bin:$PATH"

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl installed but not on PATH. Add to your shell:"
  echo "  export PATH=\"\$HOME/.fly/bin:\$PATH\""
  exit 1
fi

echo "==> flyctl installed: $(flyctl version)"
