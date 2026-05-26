#!/usr/bin/env bash
# Bootstrap SIIP on a fresh Ubuntu server (Oracle Cloud, AWS, etc.)
#
# LEGACY: the production path is Supabase + Aura + Fly (see deploy/free/).
# This script remains for self-hosting on a VPS or rebuilding the original
# local Docker stack on a server.
#
# Run from a cloned repo:
#   ./deploy/legacy/bootstrap.sh
#
# Or one-liner (clones repo + runs this):
#   curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/legacy/oracle-install.sh | bash
set -euo pipefail

LEGACY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$LEGACY_DIR/../.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f $LEGACY_DIR/docker-compose.yml -f $LEGACY_DIR/docker-compose.prod.yml"

SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  SUDO="sudo"
fi

run_apt() { $SUDO apt-get "$@"; }

echo "==> SIIP production bootstrap"
echo "    Repo: https://github.com/dogeyboy1932/armchair"

# ── Base packages ─────────────────────────────────────────────────────────────
if ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  echo "Installing curl and git…"
  run_apt update -qq
  run_apt install -y curl git ca-certificates
fi

# ── Docker ────────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker…"
  curl -fsSL https://get.docker.com | $SUDO sh
  if [[ -n "$SUDO" ]] && id -nG "${USER:-ubuntu}" 2>/dev/null | grep -qv docker; then
    $SUDO usermod -aG docker "${USER:-ubuntu}"
    echo "Added ${USER:-ubuntu} to the docker group."
  fi
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Installing Docker Compose plugin…"
  run_apt update -qq
  run_apt install -y docker-compose-plugin
fi

# ── Swap (helps Milvus on tight RAM during first boot) ────────────────────────
if [[ ! -f /swapfile ]] && [[ "$(free -m | awk '/^Mem:/{print $2}')" -lt 12000 ]]; then
  echo "Adding 4 GB swap (one-time)…"
  $SUDO fallocate -l 4G /swapfile || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
  $SUDO chmod 600 /swapfile
  $SUDO mkswap /swapfile
  $SUDO swapon /swapfile
  grep -q '/swapfile' /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
fi

# ── .env ──────────────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  cp .env.example .env
  PG_PASS="$(openssl rand -hex 16)"
  NEO_PASS="$(openssl rand -hex 12)"
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${PG_PASS}/" .env
  sed -i "s/^NEO4J_PASSWORD=.*/NEO4J_PASSWORD=${NEO4J_PASSWORD:-${NEO_PASS}}/" .env
  echo "Created .env with random passwords."
  echo "Optional: add GEMINI_API_KEY=... to .env for pre-generated explanations."
fi

# ── Host firewall ─────────────────────────────────────────────────────────────
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: inactive"; then
  $SUDO ufw allow OpenSSH
  $SUDO ufw allow 8080/tcp
  $SUDO ufw allow 80/tcp
  $SUDO ufw allow 443/tcp
  $SUDO ufw --force enable
  echo "UFW enabled: SSH + 8080 + 80 + 443."
fi

# Oracle Cloud images also use iptables rules outside UFW — open app ports there too.
if command -v iptables >/dev/null 2>&1; then
  for PORT in 8080 80 443; do
    if ! $SUDO iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
      $SUDO iptables -I INPUT -p tcp --dport "$PORT" -j ACCEPT
    fi
  done
  if command -v netfilter-persistent >/dev/null 2>&1; then
    $SUDO netfilter-persistent save >/dev/null 2>&1 || true
  elif [[ -d /etc/iptables ]]; then
    $SUDO iptables-save | $SUDO tee /etc/iptables/rules.v4 >/dev/null 2>&1 || true
  fi
  echo "Host iptables: ports 8080, 80, 443 open."
fi

# ── Start stack ───────────────────────────────────────────────────────────────
echo "Starting containers (first run downloads ~4 GB of images)…"
$COMPOSE up -d --build

echo "Waiting for services to become healthy (up to 5 min)…"
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then
    break
  fi
  if [[ $i -eq 60 ]]; then
    echo "Backend did not become healthy in time."
    echo "Check logs: $COMPOSE logs backend"
    exit 1
  fi
  sleep 5
done

# ── Seed data if empty ────────────────────────────────────────────────────────
COURSE_COUNT="$($COMPOSE exec -T postgres psql -U siip -d siip -tAc 'SELECT COUNT(*) FROM courses;' 2>/dev/null || echo 0)"
if [[ "${COURSE_COUNT// /}" == "0" ]]; then
  echo "Empty database — running seed pipeline (10–20 min first time)…"
  $COMPOSE exec -T backend python scripts/seed.py
  if grep -qE '^GEMINI_API_KEY=.+' .env 2>/dev/null; then
    $COMPOSE exec -T backend python scripts/label_categories.py
    $COMPOSE exec -T backend python scripts/build_graph.py
    $COMPOSE exec -T backend python scripts/explain_connections.py --top 50
  else
    echo "No GEMINI_API_KEY — skipping LLM batch scripts."
    echo "Graph works; users can paste a Gemini key in the UI (⚙ button)."
    $COMPOSE exec -T backend python scripts/build_graph.py
  fi
else
  echo "Database already has ${COURSE_COUNT} courses — skipping seed."
fi

# ── HTTPS reverse proxy (optional) ────────────────────────────────────────────
DOMAIN="${SIIP_DOMAIN:-}"
if [[ -n "$DOMAIN" ]]; then
  if ! command -v caddy >/dev/null 2>&1; then
    run_apt update -qq
    run_apt install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | $SUDO gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    run_apt update -qq
    run_apt install -y caddy
  fi
  $SUDO tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMAIN} {
    reverse_proxy 127.0.0.1:8080
}
EOF
  $SUDO systemctl enable caddy
  $SUDO systemctl reload caddy
  echo ""
  echo "✓ Live at: https://${DOMAIN}"
else
  PUBLIC_IP="$(curl -sf ifconfig.me 2>/dev/null || curl -sf icanhazip.com 2>/dev/null || hostname -I | awk '{print $1}')"
  echo ""
  echo "✓ Live at: http://${PUBLIC_IP}:8080"
  echo ""
  echo "Optional HTTPS: point a domain A-record here, then run:"
  echo "  SIIP_DOMAIN=your.domain ./deploy/legacy/bootstrap.sh"
fi

echo ""
echo "Health: curl http://127.0.0.1:8080/health"
