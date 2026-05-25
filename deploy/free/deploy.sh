#!/usr/bin/env bash
# One-shot full deploy: verify services → deploy backend → bootstrap data → deploy frontend.
# Re-runnable. Each step is independently idempotent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

bash deploy/free/01-verify-services.sh
bash deploy/free/02-deploy-fly.sh
bash deploy/free/04-bootstrap-data.sh   # runs scripts inside the Fly machine
bash deploy/free/03-deploy-netlify.sh

echo ""
echo "🎉 All set."
