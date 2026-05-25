#!/usr/bin/env bash
# Bootstrap the production database with the initial 33-course MechSE dataset.
# Runs entirely INSIDE the deployed Fly machine via `flyctl ssh console -C` —
# no local Python, no SciNCL on your laptop. The Fly image already has the
# model baked in, so everything runs on the cloud.
#
# This is idempotent: seed.py + build_graph.py both use upserts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ -f deploy/free/credentials.env ]] || { echo "Missing credentials.env" >&2; exit 1; }
set -a; source deploy/free/credentials.env; set +a

APP="${FLY_APP_NAME:-siip-armchair-akhil}"
export PATH="$HOME/.fly/bin:$PATH"
command -v flyctl >/dev/null 2>&1 || { echo "flyctl not found. Run 00-install-flyctl.sh" >&2; exit 1; }

run_remote() {
  local label="$1"; shift
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  $label"
  echo "  $ $*"
  echo "════════════════════════════════════════════════════════════"
  flyctl ssh console --app "$APP" -C "$*" 2>&1
}

run_remote "1/3  Seeding 33 courses (SciNCL ~1 min)" \
  "sh -c 'cd /app && python scripts/seed.py'"

run_remote "2/3  Building similarity graph (~2 min)" \
  "sh -c 'cd /app && python scripts/build_graph.py'"

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  run_remote "3a/3  Labeling topic categories with Gemini" \
    "sh -c 'cd /app && python scripts/label_categories.py'"
  run_remote "3b/3  Building topic-level similarity graph" \
    "sh -c 'cd /app && python scripts/build_topic_graph.py'"
else
  echo ""
  echo "Skipping LLM steps (no GEMINI_API_KEY in credentials.env)."
  echo "To enable later, add GEMINI_API_KEY to credentials.env and run:"
  echo "  flyctl secrets set GEMINI_API_KEY=\"\$GEMINI_API_KEY\" --app $APP"
  echo "  flyctl ssh console --app $APP -C 'sh -c \"cd /app && python scripts/label_categories.py && python scripts/build_topic_graph.py\"'"
fi

echo ""
echo "✓ Production data bootstrap complete."
