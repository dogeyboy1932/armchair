#!/usr/bin/env bash
# One-time: store FLY_API_TOKEN in GitHub Actions so pushes to main auto-deploy.
#
# Prerequisites:
#   - flyctl auth login   (or FLY_API_TOKEN in deploy/free/credentials.env)
#   - gh auth login
#
# Usage:
#   bash deploy/free/setup-github-actions.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.fly/bin:$PATH"

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl not found. Run: bash deploy/free/00-install-flyctl.sh && flyctl auth login" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) not found." >&2
  echo "Install: https://cli.github.com/  then run: gh auth login" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Not logged into GitHub. Run: gh auth login" >&2
  exit 1
fi

APP="${FLY_APP_NAME:-siip-armchair-akhil}"
REPO="${GITHUB_REPO:-dogeyboy1932/armchair}"

echo "==> Creating Fly deploy token for app: $APP"
TOKEN="$(flyctl tokens create deploy --app "$APP" --name "github-actions-deploy" --expiry 8760h 2>/dev/null | tail -1)"
if [[ -z "$TOKEN" || "$TOKEN" != FlyV1* ]]; then
  echo "Failed to create Fly deploy token. Is flyctl authenticated?" >&2
  exit 1
fi

echo "==> Storing FLY_API_TOKEN in GitHub Actions secrets for $REPO"
printf '%s' "$TOKEN" | gh secret set FLY_API_TOKEN --repo "$REPO"

echo ""
echo "✓ Done. Push to main to trigger a deploy:"
echo "  git push origin main"
echo "  # or watch: https://github.com/$REPO/actions"
