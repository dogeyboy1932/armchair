# SIIP Semantic Pipeline — Setup & Run Instructions

> **Production workflow (recommended):** Local and production share the same
> Supabase + Neo4j Aura databases. Only code/UI differ until you `git push`.
> See `deploy/free/README.md` for the full picture.
>
> ```bash
> cp deploy/free/credentials.env.example deploy/free/credentials.env
> # fill DATABASE_URL, NEO4J_URI, NEO4J_PASSWORD
> bash deploy/free/link-local-env.sh
> uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
> git push origin main   # → GitHub Actions deploys https://siip-armchair-akhil.fly.dev
> ```
>
> The sections below describe an **optional isolated Docker stack** for fully
> offline development. Skip them if you use the cloud-backed `.env` above.

## What You Already Have (Verified)
- Docker 28.5.1 ✓
- Docker Compose v2.40.1 ✓
- Python 3.12.3 ✓

You do **not** need to install anything at the OS level. All infrastructure (PostgreSQL, Neo4j,
Milvus) runs inside Docker containers. You only need to follow the steps below.

---

## Step 1 — Create Your `.env` File

Inside `akhil_app/`, copy the example file and fill in two passwords:

```bash
cp akhil_app/.env.example akhil_app/.env
```

Then open `akhil_app/.env` and set exactly these two values — everything else is pre-filled:

```
POSTGRES_PASSWORD=siip_local
NEO4J_PASSWORD=siip_local_neo4j
```

> **Neo4j password rules:** minimum 8 characters. Do not use a password that is just a dictionary
> word (Neo4j rejects simple passwords on first boot).

Leave all other values at their defaults unless you know what you're changing.

---

## Step 2 — Start the Infrastructure

From the **project root** (`SIIP/`), run:

```bash
docker compose -f akhil_app/docker-compose.yml up -d
```

This starts six containers: `etcd`, `minio`, `milvus`, `neo4j`, `postgres`, and `api`.

First run takes **3–5 minutes** — Docker is downloading images (~4 GB total). Subsequent starts
take under 30 seconds.

### Verify everything is running

```bash
docker compose -f akhil_app/docker-compose.yml ps
```

All six services should show `running` or `healthy`. If any show `exited`, see Troubleshooting below.

---

## Step 3 — Verify Each Service Individually

### PostgreSQL
```bash
docker exec -it siip-postgres psql -U siip -d siip -c "SELECT version();"
```
Expected output: a line starting with `PostgreSQL 15...`

### Neo4j
Open your browser: **http://localhost:7474**

- Username: `neo4j`
- Password: whatever you set in `.env` for `NEO4J_PASSWORD`

You should see the Neo4j Browser UI. Run this query to confirm GDS is installed:
```cypher
RETURN gds.version()
```
Expected: a version string like `"2.6.x"`. If you get an error, see Troubleshooting.

### Milvus
```bash
docker exec -it siip-milvus curl -s http://localhost:9091/healthz
```
Expected output: `OK`

---

## Step 4 — Set Up the Python Environment

From inside `akhil_app/`:

```bash
cd akhil_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> The first install will download the `malteos/scincl` model weights (~440 MB) from HuggingFace
> during your first pipeline run (not during `pip install`). Make sure you have a stable internet
> connection for Step 5.

---

## Step 5 — Seed the Database (One-Time)

This loads all 33 MechSE courses from `mechse_syllabi.json`, chunks them, embeds them with SciNCL,
and stores everything in PostgreSQL and Milvus.

```bash
# Still inside akhil_app/ with .venv active
python scripts/seed.py
```

Expected output:
```
Loading courses from mechse_syllabi.json...
  33 courses found.
[1/33] CHEM 102 — chunking...
[1/33] CHEM 102 — encoding 14 chunks with SciNCL...   ← first run downloads model here
[1/33] CHEM 102 — stored to Milvus + PostgreSQL.
...
[33/33] TAM 470 — stored.
Seed complete. 33 courses, ~420 chunks total.
```

**First run only:** SciNCL downloads ~440 MB to `akhil_app/.model_cache/`. All subsequent runs
use the cache and take seconds.

---

## Step 6 — Build the Similarity Graph (One-Time)

This computes all 528 pairwise course similarity scores (IR + vector hybrid), caches them in
PostgreSQL, and pushes edges into Neo4j. Then runs Louvain community detection and PageRank.

```bash
python scripts/build_graph.py
```

Expected output:
```
Computing pairwise scores for 33 courses (528 pairs)...
  [528/528] done.
Writing edges to Neo4j (score >= 0.25)...
  287 edges written.
Running Louvain community detection...
  6 communities found.
Running PageRank...
Graph build complete.
```

This takes **2–5 minutes** depending on your hardware.

---

## Step 7 — Start the API

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

Open **http://localhost:8080/docs** — this is the interactive Swagger UI where you can test
every endpoint directly in the browser.

---

## What You Can Now Do

| URL | What it does |
|-----|-------------|
| `http://localhost:8080/docs` | Interactive API explorer (Swagger UI) |
| `http://localhost:7474` | Neo4j Browser — visual graph, run Cypher queries |
| `http://localhost:8080/courses` | List all 33 loaded courses |
| `http://localhost:8080/similarity?a=ME410&b=ME310` | Pairwise similarity score with explanation |
| `http://localhost:8080/neighbors?course=ME410&top=10` | Top 10 most similar courses to ME410 |
| `http://localhost:8080/communities` | Louvain-detected discipline clusters |
| `http://localhost:8080/path?from=ME200&to=ME410` | Shortest conceptual path between two courses |

---

## Day-to-Day Usage

### Start everything (after first setup)
```bash
docker compose -f akhil_app/docker-compose.yml up -d
cd akhil_app && source .venv/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

### Stop everything
```bash
docker compose -f akhil_app/docker-compose.yml down
```

### Stop and wipe all data (full reset)
```bash
docker compose -f akhil_app/docker-compose.yml down -v
```
After this, repeat Steps 5 and 6.

### Add a new course via PDF
POST to `http://localhost:8080/ingest/pdf` with:
- `file`: the PDF
- `course_id`: e.g. `ME499`
- `course_name`: e.g. `Advanced Robotics`

The API will parse, chunk, embed, store, and recompute all similarity scores involving the new
course automatically.

---

## Troubleshooting

### A container shows `exited` after `docker compose ps`

Check its logs:
```bash
docker compose -f akhil_app/docker-compose.yml logs <service-name>
```
Replace `<service-name>` with `milvus`, `neo4j`, `postgres`, etc.

**Common causes:**
- **Port conflict:** another process is using port 5432, 7474, or 19530.
  Check with `sudo lsof -i :<port>`. Stop the conflicting process or change the port in
  `docker-compose.yml`.
- **Milvus exits immediately:** etcd or minio wasn't ready. Run `docker compose up -d` again —
  Milvus will retry once its dependencies are healthy.

### Neo4j `RETURN gds.version()` gives an error

GDS plugin failed to download on first boot (needs internet). Run:
```bash
docker compose -f akhil_app/docker-compose.yml restart neo4j
```
Wait 60 seconds, then try again. If it persists, check `docker logs siip-neo4j` for download errors.

### `seed.py` fails with "connection refused" on Milvus or PostgreSQL

The containers need a moment after `docker compose up` before they accept connections.
Wait 30 seconds and retry.

### HuggingFace model download is slow or fails

Set a HuggingFace mirror or download manually:
```bash
pip install huggingface_hub
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('malteos/scincl', cache_dir='.model_cache')"
```

### `build_graph.py` completes but Neo4j shows no edges

The `MIN_SCORE` threshold (default 0.25) may be filtering all edges. Temporarily lower it in `.env`:
```
MIN_SCORE=0.1
```
Then rerun `build_graph.py`.

---

## Ports Reference

| Service | Port | Used for |
|---------|------|----------|
| FastAPI | 8080 | API + Swagger UI |
| Neo4j Browser | 7474 | Visual graph explorer |
| Neo4j Bolt | 7687 | Driver connection (used internally) |
| PostgreSQL | 5432 | Used internally by API |
| Milvus | 19530 | Used internally by API |
| MinIO Console | 9001 | Milvus object storage UI (not needed) |

---

## Your Checklist

- [ ] Copied `.env.example` → `.env` and set both passwords
- [ ] `docker compose up -d` — all 6 containers running
- [ ] Neo4j Browser opens at localhost:7474 and `gds.version()` returns a version
- [ ] `python scripts/seed.py` — 33 courses loaded
- [ ] `python scripts/build_graph.py` — edges visible in Neo4j Browser
- [ ] `uvicorn` running — Swagger UI opens at localhost:8080/docs
