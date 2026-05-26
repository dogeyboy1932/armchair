# ArmChair

UIUC MechSE curriculum mapping. Finds **non-obvious cross-domain connections** between
course topics (ME 340 spring-mass ↔ ECE 206 RLC circuit — same 2nd-order ODE,
different department).

**Live:** https://siip-armchair-akhil.fly.dev
**Supervisor:** Eliot Bethke (bethke2@illinois.edu)

---

## What this is

A research tool for mapping conceptual overlap across a curriculum. Standard
similarity engines surface obvious same-domain matches (ME 340 ↔ ME 310 — both
mechanical). SIIP is built to surface the **non-obvious** ones — courses whose
topics are mathematically/structurally similar but live in different
departments. The driving insight (from supervisor Eliot Bethke): *"semantic
similarity on topic:definition strings, weighted by dissimilarity of category
composition."* That weighting is what makes the engine value cross-domain
matches over same-domain ones.

**The one-line scoring story:**

```
non_obvious_score = sem_score × category_jsd
                     ↑              ↑
                     how similar    how different
                     the topics     the disciplines
                     read           the courses span
```

A pair scores high only when both factors are high. Same-department pairs
collapse to zero on the `category_jsd` term and stop crowding the results.
The full math (TF-IDF + Dirichlet smoothing + JSD + symmetrised SciNCL cosine)
lives in `docs/ARCHITECTURE.md`.

## What you can do with it

The live site (single SPA, no build step) gives three views over the 35-course
corpus:

- **Map** — D3 force-directed graph. Node size = PageRank, color = Louvain
  community. Toggle Normal/Non-obvious to swap which signal drives edge weights.
- **Courses** — pick a course, see its neighbours ranked by hybrid *or*
  non-obvious score. Each card shows the 8-bin category distribution, driving
  terms, and a "Generate explanation" button (Gemini, on-demand, cached forever).
- **Search Topics** — keyword search over all topic texts. Expanded hits show
  semantically similar topics in *other* courses, surfaced via topic-to-topic ANN.
- **Add syllabus** (`/upload`) — drop in a PDF or TXT. Background pipeline does
  Gemini topic extraction + category labels + SciNCL embedding + scoring against
  every existing course + Louvain re-clustering, end-to-end in ~60 s.

## How it works (end-to-end, 60 seconds)

A course PDF lands at `/ingest/pdf`. The pipeline:

1. **LLM analysis** — one Gemini call returns description, learning objectives,
   topic names, one-line topic definitions, and an 8-bin category distribution
   per topic (Mechanics | Thermodynamics | Electrical | Fluids | Materials |
   Math | Chemistry | Systems). No further LLM calls during ingest.
2. **Chunk + embed** — topics become `"Course Name [SEP] Topic: definition"`
   strings; SciNCL encodes each into a 768-dim vector stored in pgvector (or
   Milvus locally).
3. **Persist** — course node + chunks + term counts + category distributions
   into Postgres; course node into Neo4j.
4. **Score** — for every other course, compute `lex_score` (TF-IDF cosine),
   `sem_score` (symmetrised SciNCL ANN), `category_jsd` (JSD over the 8-bin
   averaged distributions), then `final_score = 0.4·lex + 0.6·sem` and
   `non_obvious_score = sem · category_jsd`. All pairs cached in Postgres.
5. **Graph** — pairs above `MIN_SCORE` (0.55) become Neo4j edges; Louvain +
   PageRank re-run (with a NetworkX fallback for AuraDB Free, which lacks GDS).

**Principle: math scores, LLM explains.** Scores are deterministic. The LLM
only renders explanations *after* the math has ranked pairs — and only on user
demand (`/similarity/explain`). The Gemini key lives in the browser's
`localStorage` and is sent as `X-Api-Key`; the server never stores it.

---

## Quick start (cloud-backed local dev)

Local code talks to the same Supabase + Neo4j Aura that production uses.

```bash
cp deploy/free/credentials.env.example deploy/free/credentials.env
# fill DATABASE_URL, NEO4J_URI, NEO4J_PASSWORD, GEMINI_API_KEY
bash deploy/free/link-local-env.sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

Open http://localhost:8080. Ship changes with `git push origin main` — GitHub Actions
deploys Fly automatically.

## Optional: fully isolated local stack (legacy)

The original docker-compose stack (Postgres + Milvus + Neo4j with GDS) lives in
`deploy/legacy/`. Useful for offline development:

```bash
docker compose -f deploy/legacy/docker-compose.yml up -d
python scripts/seed.py            # load 33 courses
python scripts/build_graph.py     # compute pairwise scores + Neo4j edges
uvicorn api.main:app --port 8080 --reload
```

Set `VECTOR_BACKEND=milvus`, `POSTGRES_HOST=localhost`, `NEO4J_URI=bolt://localhost:7687`
in `.env`. See `docs/ARCHITECTURE.md` § Environment for the full variable list.

---

## Docs

| File | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | System design, file reference, scoring math, API, UI |
| `deploy/free/README.md` | Production deploy (Supabase + Aura + Fly) + CI/CD |
| `deploy/legacy/ORACLE.md` | Legacy self-host on Oracle Cloud / VPS |
| `CLAUDE.md` | Pointers for the Claude Code assistant |

## Common commands

```bash
# Re-score everything after weight changes
python scripts/build_graph.py

# Build topic-to-topic similarity (powers Topics tab)
python scripts/build_topic_graph.py

# Pre-generate LLM explanations for top non-obvious pairs
python scripts/explain_connections.py --top 50 --min-sem 0.3

# Wipe and start over (destructive)
python scripts/reset.py
```

Run any script on production with:
```bash
flyctl ssh console --app siip-armchair-akhil -C "sh -c 'cd /app && python scripts/<name>.py'"
```
