# SIIP — System Guide

A course-similarity engine for UIUC MechSE. Given any course, it finds the most topically related courses using a hybrid of keyword overlap and semantic embedding similarity, then visualises the result as an interactive graph.

---

## Architecture at a Glance

```
  Browser ──────────────────────────────────────────────────────
  public/index.html       → Force-directed similarity graph
  public/visualize.html   → 3-panel course explorer
  public/upload.html      → Ingest a new PDF syllabus

  FastAPI (api/) ────────────────────────────────────────────────
  GET  /courses            list / fetch course metadata
  GET  /similarity         pre-computed pairwise score lookup
  GET  /graph/all          full node+edge set for D3
  POST /ingest/pdf         upload a new syllabus (background job)

  Storage layer ─────────────────────────────────────────────────
  PostgreSQL   → canonical store: courses, chunks, term counts,
                 similarity cache (every pair, every score)
  Neo4j        → graph store: SIMILAR_TO edges (score ≥ MIN_SCORE),
                 Louvain communities, PageRank
  Milvus       → vector store: 768-dim SciNCL embeddings per chunk

  Scoring ────────────────────────────────────────────────────────
  Lexical  → TF-IDF cosine similarity (sparse, discriminative)
  Semantic → SciNCL cosine similarity (floor-calibrated)
  Hybrid   → α · lex + (1-α) · sem   (default α = 0.5)
```

---

## Folder & File Reference

### `config.py`
Central configuration. Every tunable constant lives here and can be overridden with environment variables (via `.env`).

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `ALPHA` | `0.5` | Weight of lexical vs semantic in hybrid score |
| `DIRICHLET_MU` | `200` | Smoothing parameter for language models |
| `MIN_SCORE` | `0.25` | Minimum hybrid score to create a Neo4j edge |
| `TOP_K_DRIVING_TERMS` | `8` | How many explaining terms to store per pair |
| `SCINCL_MODEL` | `malteos/scincl` | HuggingFace model ID |
| `SCINCL_CACHE_DIR` | `.model_cache/` | Where the downloaded model lives |
| `DATA_DIR` | `data/` | All four JSON data files |

---

### `data/`
Static input files. Nothing in here is generated — it's the raw dataset.

| File | Contents |
|------|----------|
| `mechse_syllabi.json` | 33 MechSE courses with topics, descriptions, objectives, credits |
| `topic_definitions.json` | `"COURSE_ID: topic name"` → definition string (enriches embeddings) |
| `course_info.json` | Type (core/elective), prerequisite strings for all courses |
| `instructors.json` | `course_id` → list of instructor names |

---

### `pipeline/`
Transforms raw syllabus JSON into the chunks and term counts that feed scoring and storage.

**`chunker.py`** — The most important preprocessing step.

Takes one course dict and returns `(chunks, term_counts)`.

- Builds four chunk types per course: `topic`, `definition`, `description`, `objective`
- Each chunk has a **`raw_text`** (what gets embedded — includes course name prefix so the model has context) and a **`term_text`** (what gets counted for the LM — no course name, so repeated name words don't inflate frequencies)
- Tokenises with a combined English stopword list + a custom `_DOMAIN_STOP` set that removes academic boilerplate (`university`, `syllabus`, `exam`, `sep`, etc.) which would otherwise make every course look similar to every other
- Returns `term_counts` as a `{token: count}` dict over just the content words

**`encoder.py`** — Thin wrapper around the SciNCL model.

- Loads `malteos/scincl` once (singleton) from `.model_cache/`
- Encodes a list of strings → `(N, 768)` float32 array, L2-normalised
- L2-normalisation means cosine similarity = dot product, which is what Milvus uses

**`keyphrase.py`** — Unused in the main pipeline; present for experimentation.

---

### `scoring/`
Everything that produces a number representing how similar two courses are.

**`language_model.py`** — Builds Dirichlet-smoothed unigram language models.

```
P(w | d) = (c(w,d) + μ · P(w|C)) / (|d| + μ)
```

- `build_corpus_probs()`: computes the corpus-level word probability `P(w|C)` by summing term counts across all courses
- `build_lm()`: smooths one course's counts with the corpus prior using `DIRICHLET_MU`
- `build_all_lms()`: calls both for every course; returns `{course_id: {term: probability}}`
- These LMs are passed to `driving_terms` (for explainability) and `jsd` (for reference storage). They are **not** used in the actual lexical score.

**`jsd.py`** — Two functions.

- `jsd(p, q)` — Jensen-Shannon Divergence between two probability distributions (stored in the DB as a reference metric, not used in the hybrid score)
- `lex_sim(raw_a, raw_b, idf)` — **TF-IDF cosine similarity**. Uses raw term counts (not smoothed LMs), so absent terms contribute exactly zero. IDF downweights terms that appear in many courses. This is the actual lexical component of the hybrid score.

**`driving_terms.py`** — Identifies the top terms explaining a similarity score.

```
score(w) = min(P(w|A), P(w|B)) × IDF(w)
```

- Only considers terms that appear in **both** raw vocabularies (not LM ghost-probabilities from smoothing)
- `compute_idf()` uses `log(N / (1 + df(w)))` where N = number of courses and df = document frequency

**`vector_similarity.py`** — Semantic similarity via embeddings.

- For each chunk in course A, finds the nearest chunk in course B (max cosine score via Milvus ANN)
- Averages across all A-chunks → directed A→B score
- Symmetrises: `0.5 × directed(A→B) + 0.5 × directed(B→A)`

**`hybrid_scorer.py`** — Combines everything into one score and persists it.

- `_SEM_FLOOR = 0.75`: SciNCL cosine similarity has a high floor for any two academic texts (~0.75–0.80), even unrelated ones. The calibration `(raw - 0.75) / 0.25` rescales above that floor so the semantic component is actually discriminative.
- `score_pair()`: computes lex + sem + hybrid, calls `driving_terms`, writes to PostgreSQL (always) and Neo4j (only if `final ≥ MIN_SCORE`)
- `score_all_pairs()`: iterates every N×(N-1)/2 pair; called by `build_graph.py`

---

### `storage/`
One file per database. Each is a thin client with connection management and typed query functions.

**`postgres_store.py`** — The canonical data store. Four tables:

| Table | Purpose |
|-------|---------|
| `courses` | Course metadata (name, description, prereqs, credits, type, instructors) |
| `chunks` | Raw text of every chunk, linked to its course |
| `term_counts` | `(course_id, term, count)` — the token frequencies used for scoring |
| `similarity_cache` | Every pairwise score ever computed: final, lex, sem, JSD, driving terms |

All writes use `INSERT ... ON CONFLICT DO UPDATE` (upsert), so re-running seed or ingest is safe.

**`neo4j_store.py`** — The graph store.

- Nodes: one `Course` per course
- Edges: `SIMILAR_TO` relationships with `score`, `lex_score`, `sem_score`, `jsd`, `driving_terms` properties — only created when `score ≥ MIN_SCORE`
- `run_community_detection()`: projects the graph into GDS, runs **Louvain** (writes `community` property to each node) and **PageRank** (writes `pagerank` property). These drive node colour and size in the graph view.
- `get_shortest_path()`: Cypher shortest path between any two courses — powers the path-finder feature in the graph UI
- `get_full_graph()`: returns all nodes + filtered edges for D3 rendering

**`milvus_store.py`** — The vector store.

- One collection `siip_chunks` with fields: `chunk_id`, `course_id`, `embedding` (768-dim float32)
- COSINE metric with FLAT index (exact search; fine for 33 × ~10 chunks = ~330 vectors)
- `search_in_course()`: takes a list of query vectors, returns the best cosine score against any chunk belonging to a specific course — used by `vector_similarity.py`

---

### `api/`

**`main.py`** — FastAPI app entry point.

- On startup (`lifespan`): initialises PostgreSQL schema, Neo4j uniqueness constraint, Milvus collection
- Mounts four routers under `/courses`, `/similarity`, `/graph`, `/ingest`
- Serves the three HTML pages at `/` (graph), `/visualize` (explorer), `/upload`
- Serves static assets (CSS, JS) from `public/` under `/static`

**`routes/courses.py`**
- `GET /courses` — list all courses (from PostgreSQL, ordered by sequence then ID)
- `GET /courses/{course_id}` — fetch one course by ID (case-insensitive)

**`routes/similarity.py`**
- `GET /similarity?a=...&b=...` — look up a pre-computed pairwise score from the PostgreSQL cache
- `GET /similarity/neighbors?course=...&top=N` — top-N most similar courses (from PostgreSQL cache)

**`routes/graph.py`**
- `GET /graph/all?min_score=...` — all nodes + edges for D3 rendering (from Neo4j)
- `GET /graph/path?from=...&to=...` — shortest similarity path between two courses (Neo4j Cypher)
- `GET /graph/communities` — Louvain community assignments (from Neo4j)
- `GET /graph/neighbors?course=...` — neighbours with names and driving terms (from Neo4j)

**`routes/ingest.py`** — Handles new syllabus uploads.

When a PDF is posted to `POST /ingest/pdf`, it:
1. Extracts text with `pdfplumber`
2. Runs the full pipeline in the background: chunk → embed → store in Postgres + Milvus + Neo4j
3. Re-scores this course against every other course already in the system
4. Re-runs Louvain + PageRank so graph clusters update

---

### `scripts/`

**`seed.py`** — One-time data load. Reads `mechse_syllabi.json`, runs every course through the pipeline, populates PostgreSQL and Milvus. Run this first.

**`build_graph.py`** — Scoring pass. Reads term counts from PostgreSQL, builds LMs, computes all N×(N-1)/2 pairwise scores, writes results to PostgreSQL and Neo4j, then runs Louvain + PageRank. Run this after `seed.py`.

**`reset.py`** — Drops and recreates all tables/collections. Use when you want a clean slate.

---

### `public/`
Static frontend — three single-page HTML files, no build step, no framework.

**`index.html`** (served at `/`) — Force-directed graph view.
- D3 v7 simulation with charge, link, collision, and centering forces
- Node size = normalised PageRank (range 5–21 px radius); node colour = Louvain community
- Min-similarity slider controls which edges are shown
- Click a node to highlight its neighbourhood; dim everything else
- Path-finder toolbar: enter two course IDs, see the shortest similarity chain
- Hover tooltip shows course name + score

**`visualize.html`** (served at `/visualize`) — 3-panel course explorer.
- Left panel: searchable course list (`GET /courses`)
- Middle panel: instructor card + course metadata (type, credits, prereqs, description)
- Right panel: similar courses (`GET /similarity/neighbors`) with score badges, lex/sem breakdown bars, driving-term chips, and a lightbulb modal for detailed term breakdown
- Top-K slider (1–50), score filter, "Graph View" and "Upload" nav buttons

**`upload.html`** (served at `/upload`) — Syllabus ingestion UI.
- Drag-and-drop PDF zone
- Course ID + Course Name fields
- On submit: `POST /ingest/pdf` → polls `GET /courses/{id}` every 3 s (up to 40 attempts / ~2 min) until the course appears
- On success: links back to Explorer and Graph views

---

### Infrastructure

**`docker-compose.yml`** — Spins up the three databases locally.
- PostgreSQL on port 5432
- Milvus (+ etcd + MinIO) on port 19530
- Neo4j (with GDS plugin) on ports 7474 / 7687

**`.env` / `.env.example`** — Database credentials and optional config overrides. `config.py` reads from `.env` automatically.

**`requirements.txt`** — All Python dependencies.

**`.venv/`** — Local Python virtualenv. All packages installed here; nothing system-wide.

**`.model_cache/`** — Cached HuggingFace model download. `malteos/scincl` (~420 MB) lives here so it's never re-downloaded. Delete this folder only if you want to force a fresh download.

---

## Data Flow Summary

```
New course arrives
        │
        ▼
  chunker.py          splits into topic / definition / description / objective chunks
        │                extracts term_counts {token: count}
        ├──────────────► PostgreSQL  (chunks table, term_counts table)
        │
  encoder.py          encodes topic+definition chunks → 768-dim SciNCL vectors
        │
        └──────────────► Milvus  (siip_chunks collection)

Scoring (score_pair)
        │
        ├── lex_sim()       TF-IDF cosine on raw term counts
        ├── sem_sim()       symmetrised SciNCL cosine via Milvus ANN
        ├── _calibrate_sem  subtract floor 0.75, rescale to [0,1]
        └── hybrid = 0.5·lex + 0.5·sem
                │
                ├──────────► PostgreSQL  (similarity_cache: every pair)
                └──────────► Neo4j       (SIMILAR_TO edge, only if ≥ MIN_SCORE)

After all pairs scored
        │
        └── run_community_detection()
                ├── Louvain   → c.community  (node colour in graph)
                └── PageRank  → c.pagerank   (node size in graph)
```
