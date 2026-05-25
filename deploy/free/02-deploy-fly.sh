#!/usr/bin/env bash
# Deploy the slim FastAPI backend to Fly.io.
# Backend connects to the already-seeded Supabase + Neo4j Aura.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f deploy/free/credentials.env ]]; then
  echo "Missing deploy/free/credentials.env" >&2
  exit 1
fi
set -a; source deploy/free/credentials.env; set +a

: "${DATABASE_URL:?DATABASE_URL required}"
: "${NEO4J_URI:?NEO4J_URI required}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD required}"

APP="${FLY_APP_NAME:-siip-armchair}"

# Make flyctl available even if not on PATH
export PATH="$HOME/.fly/bin:$PATH"
if ! command -v flyctl >/dev/null 2>&1; then
  bash deploy/free/00-install-flyctl.sh
fi

# Auth: prefer explicit token if provided, otherwise rely on `flyctl auth login` config
if [[ -n "${FLY_API_TOKEN:-}" ]]; then
  export FLY_ACCESS_TOKEN="$FLY_API_TOKEN"
fi

# Verify we have working credentials
if ! flyctl auth whoami >/dev/null 2>&1; then
  echo "Not authenticated to Fly.io. Run: flyctl auth login" >&2
  exit 1
fi
echo "==> Authenticated as: $(flyctl auth whoami 2>&1)"

# ── Create app if needed (idempotent) ───────────────────────────────────────
if flyctl status --app "$APP" >/dev/null 2>&1; then
  echo "==> Reusing existing Fly app: $APP"
else
  echo "==> Creating Fly app: $APP"
  flyctl apps create "$APP" --org personal
fi

# ── Patch fly.toml with the chosen app name (only if different) ──────────────
if grep -q "^app = \"$APP\"" fly.toml; then
  : # already matches
else
  echo "==> Updating fly.toml app name to: $APP"
  sed -i.bak "s/^app = .*/app = \"$APP\"/" fly.toml
  rm -f fly.toml.bak
fi

# ── Set secrets ─────────────────────────────────────────────────────────────
echo "==> Setting Fly secrets…"
SECRETS=(
  "DATABASE_URL=$DATABASE_URL"
  "NEO4J_URI=$NEO4J_URI"
  "NEO4J_USER=${NEO4J_USER:-neo4j}"
  "NEO4J_PASSWORD=$NEO4J_PASSWORD"
)
# GEMINI_API_KEY enables LLM-dependent endpoints (topic labeling, PDF ingest
# topic extraction, on-demand explanations). Optional but required for parity
# with local capabilities.
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  SECRETS+=("GEMINI_API_KEY=$GEMINI_API_KEY")
fi

flyctl secrets set --app "$APP" --stage "${SECRETS[@]}" >/dev/null

# ── Deploy ───────────────────────────────────────────────────────────────────
echo "==> Building & deploying (5-10 min on first deploy)…"
flyctl deploy --app "$APP" --remote-only

# ── Verify ──────────────────────────────────────────────────────────────────
URL="https://${APP}.fly.dev"
echo ""
echo "==> Waiting for $URL/health to return 200…"
for i in $(seq 1 30); do
  if curl -sf "${URL}/health" >/dev/null; then
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  ✓ SIIP is live at: $URL"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "  Graph view:  $URL"
    echo "  API docs:    $URL/docs"
    echo "  Logs:        flyctl logs --app $APP"
    echo "  Status:      flyctl status --app $APP"
    exit 0
  fi
  printf '.'
  sleep 5
done

echo ""
echo "Health check did not pass in 150s. Investigate with:"
echo "  flyctl logs --app $APP"
exit 1
