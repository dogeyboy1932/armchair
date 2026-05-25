#!/usr/bin/env bash
# Deploy the static frontend (public/) to Netlify.
#
# The frontend reads window.__SIIP_API__ from a generated config.js so it can
# talk to the Fly-hosted backend. We build into a temp directory so the source
# public/ stays committable and the Fly image keeps its own embedded copy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f deploy/free/credentials.env ]]; then
  echo "Missing deploy/free/credentials.env" >&2
  exit 1
fi
set -a; source deploy/free/credentials.env; set +a

# Derive the backend URL. Prefer explicit override, else fly app name.
FLY_APP="${FLY_APP_NAME:-siip-armchair}"
API_URL="${SIIP_API_URL:-https://${FLY_APP}.fly.dev}"
SITE_NAME="${NETLIFY_SITE_NAME:-siip-armchair}"

# ── Install Netlify CLI locally if needed (avoids global-prefix permission issues)
LOCAL_NETLIFY_DIR="deploy/free/.netlify"
LOCAL_NETLIFY_BIN="$ROOT/$LOCAL_NETLIFY_DIR/node_modules/.bin"
export PATH="$LOCAL_NETLIFY_BIN:$PATH"

if ! command -v netlify >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found. Install Node.js first (https://nodejs.org)." >&2
    exit 1
  fi
  echo "==> Installing Netlify CLI into $LOCAL_NETLIFY_DIR …"
  mkdir -p "$LOCAL_NETLIFY_DIR"
  # Override any global prefix from user/system .npmrc that points at a read-only path
  npm install --prefix "$LOCAL_NETLIFY_DIR" --no-save --silent netlify-cli
fi

# ── Auth: prefer NETLIFY_AUTH_TOKEN, else require a prior `netlify login`
# `netlify status` always exits 0; use an authenticated API call as a real check.
if [[ -n "${NETLIFY_AUTH_TOKEN:-}" ]]; then
  export NETLIFY_AUTH_TOKEN
fi
if ! netlify api listSites --data '{"page":1,"per_page":1}' >/dev/null 2>&1; then
  echo ""
  echo "Not authenticated to Netlify."
  echo "Run this in your terminal (opens a browser):"
  echo "    netlify login"
  echo "Then re-run: bash deploy/free/03-deploy-netlify.sh"
  exit 1
fi
WHOAMI="$(netlify api getCurrentUser 2>/dev/null | grep -o '"email":"[^"]*"' | sed -n 's/"email":"\(.*\)"/\1/p' | head -1 || true)"
echo "==> Netlify auth OK${WHOAMI:+ (as $WHOAMI)}"

# ── Build into a temp directory so public/ stays untouched ──────────────────
DIST="$(mktemp -d -t siip-netlify-XXXXXX)"
trap 'rm -rf "$DIST"' EXIT
cp -r public/. "$DIST"/

# Generate runtime config that points the SPA at the Fly backend.
cat > "$DIST/config.js" <<EOF
// Generated at deploy time by deploy/free/03-deploy-netlify.sh
// Frontend reads this before any other script.
window.__SIIP_API__ = "${API_URL%/}";
EOF
echo "==> Built dist at $DIST (config.js -> $API_URL)"

# Ensure netlify.toml is included in the dist for the redirect rules.
cp netlify.toml "$DIST"/netlify.toml 2>/dev/null || true

# ── Create / look up the Netlify site (use the project ID, not the slug) ────
lookup_site_id() {
  netlify api listSites 2>/dev/null \
    | python3 -c "
import sys, json
name = '$SITE_NAME'
try:
    for s in json.load(sys.stdin):
        if s.get('name') == name:
            print(s['id']); break
except Exception:
    pass
"
}

SITE_ID="$(lookup_site_id || true)"
if [[ -z "$SITE_ID" ]]; then
  echo "==> Creating Netlify site: $SITE_NAME"
  CREATE_OUT="$(netlify sites:create --name "$SITE_NAME" --disable-linking 2>&1)"
  echo "$CREATE_OUT"
  SITE_ID="$(echo "$CREATE_OUT" | grep -oE 'Project ID:[[:space:]]+[a-f0-9-]+' | awk '{print $3}' | head -1 || true)"
  if [[ -z "$SITE_ID" ]]; then
    echo "Could not determine site id after creation." >&2
    exit 1
  fi
else
  echo "==> Reusing existing Netlify site: $SITE_NAME ($SITE_ID)"
fi

# ── Deploy (production) ─────────────────────────────────────────────────────
echo "==> Deploying $DIST to Netlify site $SITE_NAME ($SITE_ID) …"
netlify deploy \
  --dir "$DIST" \
  --site "$SITE_ID" \
  --prod \
  --message "siip frontend (api=$API_URL)"

FRONT_URL="https://${SITE_NAME}.netlify.app"

# ── Verify the deployed page loads and config.js is wired correctly ─────────
echo ""
echo "==> Verifying ${FRONT_URL}/config.js …"
for i in $(seq 1 12); do
  if curl -sf "${FRONT_URL}/config.js" | grep -q "$API_URL"; then
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  ✓ SIIP frontend is live at: $FRONT_URL"
    echo "    talking to backend:        $API_URL"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "  Update API URL: edit SIIP_API_URL in deploy/free/credentials.env"
    echo "  Redeploy:       bash deploy/free/03-deploy-netlify.sh"
    exit 0
  fi
  printf '.'
  sleep 5
done

echo ""
echo "config.js verification failed; check https://app.netlify.com/sites/$SITE_NAME" >&2
exit 1
