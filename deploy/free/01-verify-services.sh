#!/usr/bin/env bash
# Verify Supabase + Neo4j Aura are reachable and have the right extensions.
# Does NOT run any seed locally — seeding happens on Fly after deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f deploy/free/credentials.env ]]; then
  echo "Missing deploy/free/credentials.env. Copy from credentials.env.example and fill in." >&2
  exit 1
fi
set -a; source deploy/free/credentials.env; set +a

: "${DATABASE_URL:?DATABASE_URL required (Supabase Postgres URL)}"
: "${NEO4J_URI:?NEO4J_URI required (Neo4j Aura URI)}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD required}"

echo "==> Verifying Supabase + installing pgvector extension"
python3 - <<PY
import os, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
cur  = conn.cursor()
cur.execute("SELECT version()")
print("  Postgres :", cur.fetchone()[0].split(",")[0])
cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
conn.commit()
cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
print("  pgvector :", cur.fetchone()[0])
cur.close(); conn.close()
PY

echo ""
echo "==> Verifying Neo4j Aura"
python3 - <<PY
import os
from neo4j import GraphDatabase
drv = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]),
)
with drv.session() as s:
    print("  Aura :", "reachable" if s.run("RETURN 1 AS ok").single()["ok"] == 1 else "unreachable")
drv.close()
PY

echo ""
echo "✓ Services healthy. Next: bash deploy/free/02-deploy-fly.sh"
