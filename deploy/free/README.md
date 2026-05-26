# SIIP production deploy: Supabase + Neo4j Aura + Fly.io

## How local and production relate

**One set of cloud databases. Two places the code runs.**

| | Local (`uvicorn --reload`) | Production (`siip-armchair-akhil.fly.dev`) |
|---|---|---|
| **Code / UI** | Your working copy | Deployed Docker image on Fly |
| **Postgres + pgvector** | Supabase (shared) | Supabase (same) |
| **Neo4j graph** | Aura (shared) | Aura (same) |
| **SciNCL / scripts** | Your laptop (optional) | Fly machine (always on) |

```bash
# 1. One-time: fill cloud credentials
cp deploy/free/credentials.env.example deploy/free/credentials.env

# 2. Point local .env at the same Supabase + Aura as production
bash deploy/free/link-local-env.sh

# 3. Develop locally against live data
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload

# 4. Ship code/UI changes — one push deploys Fly
git push origin main
```

**What syncs automatically:** anything in git (Python, HTML, CSS, scoring weights in
`config.py`, seed JSON in `data/`). GitHub Actions rebuilds and rolls out Fly on
every push to `main`.

**What does NOT sync via git:** data you create only on the live site (e.g. PDF
upload on production). That goes straight into the shared cloud DBs — your local
`uvicorn` will see it too once you refresh, because it's the same Supabase/Aura.

**Optional:** the original `docker-compose` stack lives in `deploy/legacy/` for
fully isolated offline work. It is not the primary dev path when using
cloud-backed `.env`.

---

Production is a **true clone of local** in features and maintenance scripts.
Heavy ops (SciNCL embed, PDF ingest, graph builds) can run on Fly via
`flyctl ssh console` so your laptop doesn't need the model loaded.

```
┌──────────────────────────────────────────────────────────┐
│  Browser ──► Fly (FastAPI + UI + SciNCL)                 │
│                       │                                  │
│                       ├──► Supabase (Postgres + pgvector)│
│                       └──► Neo4j Aura                    │
└──────────────────────────────────────────────────────────┘
```

| Service | Plan | Used for |
|---|---|---|
| Fly.io | Hobby ($5/mo credit) | UI + API + SciNCL + scripts (1 always-on 2GB VM) |
| Supabase | Free | Postgres 17 + pgvector |
| Neo4j Aura | Free | Course similarity graph |
| Gemini | Free tier | Topic extraction, category labels, explanations |

Net cost: **~$0/month** (Fly's 2 GB machine is ~$3.89/mo, covered by the $5 hobby credit).

---

## Architecture notes

- **One service**: Fly serves both the static UI (`ui/`) and the FastAPI
  endpoints from the same origin, so there's no CORS, no CDN, no `config.js`
  rewriting. Just one URL.
- **One Docker image**, baked with SciNCL (420 MB) + CPU PyTorch + pdfplumber +
  all scripts. Cold starts skip the model download.
- **One always-on Fly machine** (`min_machines_running = 1`) so background
  ingest tasks always have a host.
- **`scripts/` is included in the image**, so any local pipeline operation runs
  on Fly with `flyctl ssh console -C "python scripts/<name>.py"`.
- **No local Postgres / Neo4j / Milvus needed** to operate production. Only
  needed if you actively want a second copy locally for development.

---

## First-time setup (~10 min of signups)

### 1. Supabase
1. https://supabase.com → New project → save the DB password.
2. Project Settings → Database → Connection string → URI tab → "Direct connection".
3. Replace `<your-password>` with the saved password → paste as `DATABASE_URL`
   in `deploy/free/credentials.env`.

### 2. Neo4j AuraDB Free
1. https://console.neo4j.io → New instance → AuraDB Free → **download the
   credentials file** (shown only once).
2. Paste into `credentials.env`: `NEO4J_URI`, `NEO4J_USER` (often `neo4j`,
   sometimes the instance ID), `NEO4J_PASSWORD`.
3. *Caveat: Aura Free pauses after 3 days idle. Hit `/health` weekly to keep it up.*
4. *Caveat: Aura Free has no GDS plugin, so `storage/neo4j/store.py` tries
   `gds.*` first and falls back to NetworkX Louvain + PageRank computed in
   the API process. Same results, same edge weights, just runs in Python.*

### 3. Fly.io
1. https://fly.io → signup (GitHub OAuth) → add a credit card (required for fraud
   prevention, not charged inside the $5/mo hobby credit).
2. `bash deploy/free/00-install-flyctl.sh` then `flyctl auth login` (browser flow).

### 4. Gemini API key (optional but recommended)
1. https://aistudio.google.com/apikey → create key.
2. Paste as `GEMINI_API_KEY` in `credentials.env`, **or** paste it in the UI's
   Settings dialog at runtime — both work. With neither, PDF ingest, topic
   labeling, and on-demand explanations return 503. Pure similarity
   (hybrid + neighbors + graph view) still works.

### 5. Fill `credentials.env`
```bash
cp deploy/free/credentials.env.example deploy/free/credentials.env
$EDITOR deploy/free/credentials.env
```

---

## Deploy

You have two options depending on what you've changed:

**A. From your laptop (first time / when you want to watch logs):**
```bash
bash deploy/free/deploy.sh
```

**B. From GitHub (continuous, hands-off):**
Push to `main`. The workflow in `.github/workflows/deploy-fly.yml` rebuilds &
deploys automatically. See § GitHub Actions below for the one-time secret setup.

The laptop path runs three steps:

| Step | What | Where it runs | Time |
|---|---|---|---|
| `01-verify-services.sh` | Test Supabase + Aura, install `vector` extension | Locally (one psycopg2 call) | 5 s |
| `02-deploy-fly.sh` | Build full image (SciNCL, torch, pdfplumber, UI), push, deploy, set secrets | Fly build + Fly machine | 8–12 min |
| `04-bootstrap-data.sh` | Seed 33 courses, build similarity graph, label categories, build topic graph | **All on Fly** via `fly ssh` | 5–10 min |

After it finishes, the app lives at:
- `https://<FLY_APP_NAME>.fly.dev`  ← UI + API on the same origin

---

## Day-to-day maintenance (all on Fly, no local Python needed)

Every script in `scripts/` runs identically inside the Fly machine. The pattern:

```bash
flyctl ssh console --app <FLY_APP_NAME> -C "sh -c 'cd /app && python scripts/<name>.py [args]'"
```

Common ops:

```bash
APP=siip-armchair-akhil

# Re-build similarity graph after weight tweaks
flyctl ssh console --app $APP -C "sh -c 'cd /app && python scripts/build_graph.py'"

# (re)label topics with categories + tags via Gemini
flyctl ssh console --app $APP -C "sh -c 'cd /app && python scripts/label_categories.py'"

# Build topic-level similarity (powers Topics tab cross-domain hits)
flyctl ssh console --app $APP -C "sh -c 'cd /app && python scripts/build_topic_graph.py'"

# Re-embed everything with SciNCL
flyctl ssh console --app $APP -C "sh -c 'cd /app && python scripts/backfill_embeddings.py'"

# Wipe + start over
flyctl ssh console --app $APP -C "sh -c 'cd /app && python scripts/reset.py'"

# Interactive shell on the production machine
flyctl ssh console --app $APP
# (then inside: cd /app && python ...)

# Live tail logs
flyctl logs --app $APP

# Restart machine
flyctl apps restart $APP
```

### Adding a course via PDF upload
Just use the **Upload** button in the frontend. The Fly machine handles the
whole pipeline (Gemini topic extraction → SciNCL embedding → scoring → Neo4j
update) in the background. Poll `/ingest/status/<course_id>` from the UI.

### Redeploying after code changes
```bash
bash deploy/free/02-deploy-fly.sh
```
Idempotent; only the changed layers are rebuilt/pushed.

---

## Where things live

| What | Where |
|---|---|
| UI (`ui/index.html`, `ui/upload.html`) | Served by FastAPI on Fly |
| API process | Fly machine (Chicago `ord`) |
| SciNCL model weights | Baked into Docker image at `/app/.model_cache` |
| LLM + scripts | `/app/scripts/`, `/app/llm/` inside Fly machine |
| `courses`, `chunks`, `term_counts`, `similarity_cache`, `topic_*` | Supabase Postgres |
| `chunk_embeddings` (pgvector) | Supabase Postgres |
| `Course` nodes + `SIMILAR_TO` edges | Neo4j Aura |

---

## Costs (per month)

| Service | Tier limit | Actual usage | Cost |
|---|---|---|---|
| Fly | $5 hobby credit | 1 × 2GB always-on (~$3.89) | $0 |
| Supabase | 500 MB DB | ~30 MB | $0 |
| Neo4j Aura | 200K nodes | 35 nodes | $0 |
| Gemini | Free tier rate limit | A few hundred calls/mo | $0 |

**Total: $0/month** under realistic research workload.

---

## Optional: running a local copy too

The codebase still supports a local-only run (Milvus + Postgres + Neo4j via
the legacy `docker-compose`). Set `VECTOR_BACKEND=milvus` in `.env` and:
```bash
docker compose -f deploy/legacy/docker-compose.yml up -d
python scripts/seed.py
uvicorn api.main:app --reload
```
Production and local are independent stacks — changes to one don't affect the
other. Use local for iterating on scoring math without touching production.

---

## GitHub Actions (CI/CD)

Every push to `main` triggers a Fly redeploy (API + UI + SciNCL in one image).
Live URL: **https://siip-armchair-akhil.fly.dev**

| Workflow | Trigger | Effect |
|---|---|---|
| `.github/workflows/deploy-fly.yml` | Push to `main`, or manual run | Rebuild Fly image, roll out, smoke-test `/health` |

### One-time secret setup

If Actions shows **"All jobs have failed"**, the usual cause is a missing
`FLY_API_TOKEN` secret — the deploy step fails before the Docker build starts.

**Option A — automated (recommended):**
```bash
flyctl auth login
gh auth login                                # https://cli.github.com/
bash deploy/free/setup-github-actions.sh
```

**Option B — manual:**
```bash
flyctl tokens create deploy --app siip-armchair-akhil --name github-actions --expiry 8760h
```
Copy the `FlyV1 fm2_...` line and store it as `FLY_API_TOKEN` in
[GitHub → Settings → Secrets → Actions](https://github.com/dogeyboy1932/armchair/settings/secrets/actions).

### Verify

```bash
git commit --allow-empty -m "ci: trigger deploy" && git push origin main
```

Watch <https://github.com/dogeyboy1932/armchair/actions>. A green run means the
live URL is serving the latest `main` commit.
