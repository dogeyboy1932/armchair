#!/usr/bin/env bash
# One-command Oracle (or any Ubuntu VPS) install.
#
# LEGACY: production path is Supabase + Aura + Fly (see deploy/free/).
# Use this only for self-hosting on a VPS.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/legacy/oracle-install.sh | bash
#
# With Gemini key for pre-generated explanations:
#   GEMINI_API_KEY=your-key curl -fsSL .../deploy/legacy/oracle-install.sh | bash
set -euo pipefail

REPO="https://github.com/dogeyboy1932/armchair.git"
DIR="${SIIP_DIR:-$HOME/armchair}"
BRANCH="${SIIP_BRANCH:-main}"

SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  SUDO="sudo"
fi

echo "==> SIIP one-command install"
echo "    Cloning into: $DIR"

if ! command -v git >/dev/null 2>&1; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y git curl ca-certificates
fi

if [[ -d "$DIR/.git" ]]; then
  echo "Repo exists — pulling latest…"
  git -C "$DIR" pull origin "$BRANCH" || true
else
  git clone --branch "$BRANCH" --depth 1 "$REPO" "$DIR"
fi

cd "$DIR"
chmod +x deploy/legacy/bootstrap.sh

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  if [[ ! -f .env ]]; then
    cp .env.example .env
  fi
  if grep -q '^GEMINI_API_KEY=' .env 2>/dev/null; then
    sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${GEMINI_API_KEY}|" .env
  else
    echo "GEMINI_API_KEY=${GEMINI_API_KEY}" >> .env
  fi
  echo "GEMINI_API_KEY set from environment."
fi

exec ./deploy/legacy/bootstrap.sh
