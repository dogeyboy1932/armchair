#!/usr/bin/env bash
# One-shot full deploy: verify services → deploy backend → bootstrap data.
# Re-runnable. Each step is independently idempotent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

bash deploy/free/01-verify-services.sh
bash deploy/free/02-deploy-fly.sh
bash deploy/free/04-bootstrap-data.sh   # runs scripts inside the Fly machine

echo ""
echo "🎉 All set."
