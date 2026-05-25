# SIIP production deploy: Supabase + Neo4j Aura + Fly.io

Production is a **true clone of local** — same features, same maintenance ops, same
scripts. The only difference is where the boxes run. No "compute locally and
push": everything (SciNCL embedding, PDF ingest, topic graph builds, category
labeling) happens on Fly.

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

- **One service**: Fly serves both the static UI (`public/`) and the FastAPI
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
deploys automatically. See `deploy/free/GITHUB_ACTIONS.md` for the one-time
secret setup.

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
| UI (`public/index.html`, `public/upload.html`) | Served by FastAPI on Fly |
| API process | Fly machine (Chicago `ord`) |
| SciNCL model weights | Baked into Docker image at `/app/.model_cache` |
| Pipeline + scripts | `/app/scripts/`, `/app/pipeline/` inside Fly machine |
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
docker-compose). Set `VECTOR_BACKEND=milvus` in `.env` and:
```bash
docker-compose up -d
python scripts/seed.py
uvicorn api.main:app --reload
```
Production and local are independent stacks — changes to one don't affect the
other. Use local for iterating on scoring math without touching production.
