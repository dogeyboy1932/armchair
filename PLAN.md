# SIIP Semantic Pipeline — Comprehensive Implementation Plan

## 0. What This Is (and Is Not)

This system is a **standalone, locally-runnable semantic similarity engine** for university course syllabi.
It lives entirely in `akhil_app/` and runs via Docker Compose. The existing `aws/` pipeline (Gemini topic
extraction + DynamoDB) is left untouched; the two systems are independent. This system is the *mathematically
rigorous* replacement for the LLM-based connection scoring.

**Core objective:** given two courses, produce a similarity score that is deterministic, bidirectional,
explainable, and grounded in Information Retrieval theory — not LLM intuition.

---

## 1. Holes Punched in the Original Plan (and Fixes)

### H1 — KL-Divergence is Asymmetric
`D_KL(P || Q) ≠ D_KL(Q || P)`. Using it raw means "ME410 → ME310" gets a different score than
"ME310 → ME410", which makes no sense for an undirected similarity graph.

**Fix:** Use Jensen-Shannon Divergence (JSD), which is the symmetric, bounded cousin:
```
M = 0.5 * (P + Q)
JSD(P, Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
```
JSD ∈ [0, log(2)] (or [0, 1] when using log base 2). Convert to similarity: `lex_sim = 1 - JSD(P, Q)`.

### H2 — Raw KL-Divergence is Unbounded
The original plan proposes "lower KL = higher similarity" but gives no normalization. When P(w|C) → 0
for a term, KL → ∞.

**Fix:** JSD solves this automatically since M = 0.5*(P+Q) is never zero when either P or Q is nonzero.

### H3 — No Actual PDF Syllabi Exist in the Repo
The project has `mechse_syllabi.json` with 33 courses (1,078 topic strings + descriptions + objectives),
but no PDFs.

**Fix:** Build two ingestion paths:
- **Path A (seed):** Process `mechse_syllabi.json` directly — this is the primary data source.
- **Path B (PDF):** `pdfplumber`-based ingestion for future syllabus uploads (same chunking logic, different parser).

### H4 — SciNCL is Trained on Paper Abstracts, Not Course Topics
`malteos/scincl` uses citation-network contrastive learning on S2ORC scientific paper abstracts.
Our input is topic strings like "steady-state conduction" — much shorter and less structured than abstracts.

**Fix:** Use SciNCL as designed but feed it the concatenation of topic name + definition text when available:
`"{topic_name}: {definition_text}"`. For courses with no definitions, use `"{course_name} [SEP] {topic_string}"`.
This is well within SciNCL's intended use case.

### H5 — "SciNCL + KL-Div" Relationship is Undefined
The original plan mentions both without saying how they combine into a final score.

**Fix:** Explicit two-component hybrid score:
```
final_sim(A, B) = α * lex_sim(A, B)  +  (1-α) * sem_sim(A, B)
```
Where:
- `lex_sim` = `1 - JSD(P_A, P_B)` — IR language model score (term overlap)
- `sem_sim` = mean of top-k cosine similarities between course A chunks and course B chunks via Milvus
- `α` = configurable weight (default 0.4), tunable in `.env`

The two components are **complementary**: `lex_sim` catches literal term overlap; `sem_sim` catches
conceptual overlap even when vocabulary differs (the lexical gap problem).

### H6 — Connections Are Only Computed at Upload Time (One-Directional)
The LLM approach only scores new topics against existing ones. Old topics never learn about new courses.

**Fix:** Batch recomputation. Every time a new course is added, all N×M pairs involving the new course
are recomputed and stored as symmetric edges in Neo4j. Full graph is always consistent.

### H7 — Milvus is Not a Simple `pip install`
Milvus Standalone requires etcd (distributed config store) and MinIO (object storage) as dependencies.
This is non-trivial to set up manually.

**Fix:** Provide a `docker-compose.yml` that brings up Milvus + etcd + MinIO as a unit, plus Neo4j and
PostgreSQL. The user runs one command.

### H8 — Neo4j Louvain Requires the GDS Plugin
The Graph Data Science (GDS) library is not included in the base `neo4j` Docker image.

**Fix:** Use `neo4j/neo4j` image with `NEO4J_PLUGINS=["graph-data-science"]` env var, which auto-downloads GDS.

### H9 — Score Threshold for Neo4j Edges is Undefined
Storing all N² edges at 33 courses = 528 edges. At 1,000 courses = 499,500 edges. Need a cutoff.

**Fix:** Store only edges where `final_sim ≥ 0.25` (configurable). At 33 courses this keeps ~200-300
meaningful edges and discards noise.

### H10 — PostgreSQL vs SQLite for Local Dev
PostgreSQL in Docker adds memory overhead and complexity for what is essentially a metadata store.

**Fix:** Keep PostgreSQL (user specified it and it's a Docker service anyway). But keep the schema minimal.

### H11 — Driving Terms Need a Clean Formula
"TF-IDF × match_weight" is hand-wavy.

**Fix:** Driving terms are the top-k terms by **pointwise intersection weight**:
```
driving_score(w) = min(P(w|A), P(w|B)) * IDF(w)
```
This rewards terms that appear meaningfully in *both* courses and are not stopwords (IDF penalizes ubiquitous terms).
Return top 5 driving terms per edge.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                              │
│  mechse_syllabi.json (seed)  OR  PDF upload (future)           │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     INGESTION PIPELINE                          │
│  1. Parse → raw text per course                                 │
│  2. Chunk → atomic concept units (topic + definition)           │
│  3. KeyBERT → keyphrases per chunk                              │
│  4. SciNCL → 768-dim embedding per chunk                        │
│  5. Store chunks + embeddings → Milvus                          │
│  6. Store course metadata + term corpus → PostgreSQL            │
└───────┬────────────────────────────────────────┬────────────────┘
        │                                        │
        ▼                                        ▼
┌───────────────┐                    ┌───────────────────────────┐
│    MILVUS     │                    │       POSTGRESQL          │
│ (768-dim vecs)│                    │  courses, chunks,         │
│  ANN search   │                    │  term_counts, query_logs  │
└───────┬───────┘                    └─────────────┬─────────────┘
        │                                          │
        └─────────────────┬────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SCORING LAYER                              │
│                                                                 │
│  For each course pair (A, B):                                   │
│                                                                 │
│  [IR Branch]                                                    │
│  - Build Dirichlet-smoothed unigram LM for A and B             │
│  - Compute JSD(P_A, P_B)  →  lex_sim = 1 - JSD/log(2)         │
│  - Extract driving_terms via pointwise intersection weight      │
│                                                                 │
│  [Vector Branch]                                                │
│  - Query Milvus: for each chunk in A, find top-k from B        │
│  - Average cosine similarities  →  sem_sim                     │
│                                                                 │
│  final_sim = α * lex_sim + (1-α) * sem_sim                     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         NEO4J GRAPH                             │
│  Nodes: Course {id, name, description}                          │
│  Edges: SIMILAR_TO {score, lex_score, sem_score,                │
│                     kl_div, driving_terms}                      │
│  Algorithms: Louvain community detection, PageRank centrality   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          FASTAPI                                 │
│  GET  /courses                       — list all courses         │
│  GET  /similarity?a=ME410&b=ME310    — pairwise score           │
│  GET  /neighbors?course=ME410&top=10 — top similar courses      │
│  GET  /path?from=ME101&to=ME410      — shortest concept path    │
│  GET  /communities                   — Louvain clusters         │
│  POST /ingest/pdf                    — upload new PDF syllabus  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Mathematical Details

### 3A. Corpus Construction per Course

For course `d`, the **term corpus** is built from:
- All topic strings (tokenized, lowercased, stopwords removed)
- Definition text entries where available
- Course description and objectives

Term count: `c(w, d)` = raw frequency of token `w` in course `d`'s corpus.
Corpus-level: `P(w|C) = Σ_d c(w,d) / Σ_d |d|`

### 3B. Dirichlet Smoothed Language Model

```
P(w | d) = [c(w, d) + μ * P(w|C)] / [|d| + μ]
```

- `μ` = Dirichlet prior (default: 2000, tunable in `.env`)
- Handles zero-counts: a term absent from a course still has nonzero probability via `P(w|C)`
- Normalizes for document length: long courses don't dominate

### 3C. Jensen-Shannon Divergence (Symmetric KL)

```
M(w) = 0.5 * P(w|A) + 0.5 * P(w|B)

JSD(A, B) = 0.5 * Σ_w P(w|A) * log[P(w|A) / M(w)]
           + 0.5 * Σ_w P(w|B) * log[P(w|B) / M(w)]

lex_sim(A, B) = 1 - JSD(A, B) / log(2)    ∈ [0, 1]
```

Sum only over the union vocabulary of A and B (avoids full-corpus loop).

### 3D. Semantic Similarity via SciNCL + Milvus

Each chunk `c_i` from course `A` is a 768-dim vector `v_i`.

```
sem_sim(A, B) = (1 / |chunks_A|) * Σ_{i ∈ A} max_{j ∈ B} cosine(v_i, v_j)
```

Implementation: for each chunk in A, query Milvus (filtered to course B) for top-1 cosine neighbor.
Average those max-cosines. This is asymmetric in itself, so symmetrize:

```
sem_sim(A, B) = 0.5 * sem_sim_directed(A→B) + 0.5 * sem_sim_directed(B→A)
```

### 3E. Hybrid Final Score

```
final_sim(A, B) = α * lex_sim(A, B) + (1 - α) * sem_sim(A, B)
```

Default `α = 0.4` (slightly favors semantic over lexical, since the lexical signal is sparse
in short topic lists). Configurable in `.env`.

### 3F. Driving Terms (Explainability)

```
driving_score(w) = min(P(w|A), P(w|B)) * log(N / df(w))
```

Where `df(w)` = number of courses containing `w`, `N` = total courses.
Returns top-5 terms. These are terms that *both* courses care about *and* are discriminative.

---

## 4. Data Flow: What Gets Stored Where

| Store | What | Key |
|-------|------|-----|
| PostgreSQL `courses` | id, name, description, prereqs, credits | `course_id` |
| PostgreSQL `chunks` | course_id, chunk_id, raw_text, keyphrases | `chunk_id` |
| PostgreSQL `term_counts` | course_id, term, count | (course_id, term) |
| PostgreSQL `similarity_cache` | course_a, course_b, scores, driving_terms | (a, b) |
| Milvus collection `chunks` | 768-dim embedding + chunk_id + course_id metadata | auto |
| Neo4j Node `Course` | id, name, community_id, pagerank | `id` |
| Neo4j Edge `SIMILAR_TO` | score, lex_score, sem_score, kl_div, driving_terms | — |

---

## 5. File Structure

```
akhil_app/
├── PLAN.md                        # This file
├── SETUP.md                       # How to run
├── .env.example                   # Template for .env
├── docker-compose.yml             # Milvus + Neo4j + PostgreSQL
├── requirements.txt
│
├── pipeline/
│   ├── __init__.py
│   ├── seed.py                    # Ingest mechse_syllabi.json → all stores
│   ├── pdf_parser.py              # pdfplumber: PDF → raw text
│   ├── chunker.py                 # text → list of {chunk_id, text, keyphrases}
│   ├── keyphrase.py               # KeyBERT keyphrase extraction
│   └── encoder.py                 # SciNCL: text → 768-dim numpy array
│
├── storage/
│   ├── __init__.py
│   ├── postgres_store.py          # DDL + CRUD for PostgreSQL
│   ├── milvus_store.py            # Collection schema, insert, query
│   └── neo4j_store.py             # Cypher helpers: upsert nodes/edges, run GDS
│
├── scoring/
│   ├── __init__.py
│   ├── language_model.py          # Build Dirichlet-smoothed LM per course
│   ├── jsd.py                     # JSD + lex_sim computation
│   ├── vector_similarity.py       # Milvus-based sem_sim per course pair
│   ├── driving_terms.py           # Pointwise intersection weight
│   └── hybrid_scorer.py           # Combine into final_sim; write to PG + Neo4j
│
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, lifespan, CORS
│   └── routes/
│       ├── courses.py             # GET /courses
│       ├── similarity.py          # GET /similarity, GET /neighbors
│       ├── graph.py               # GET /path, GET /communities
│       └── ingest.py              # POST /ingest/pdf
│
└── scripts/
    ├── build_graph.py             # CLI: compute all pairwise scores → Neo4j
    └── reset.py                   # CLI: wipe all stores and re-seed
```

---

## 6. Docker Compose Services

| Service | Image | Port(s) | Purpose |
|---------|-------|---------|---------|
| `etcd` | `quay.io/coreos/etcd:v3.5.5` | internal | Milvus config store |
| `minio` | `minio/minio:RELEASE.2023-03-20T20-16-18Z` | 9000, 9001 | Milvus object store |
| `milvus` | `milvusdb/milvus:v2.3.3` | **19530** | Vector DB |
| `neo4j` | `neo4j:5.15-community` | **7474**, **7687** | Graph DB (with GDS) |
| `postgres` | `postgres:15` | **5432** | Relational metadata |
| `api` | built from `akhil_app/` | **8080** | FastAPI |

All services on a shared `siip_net` bridge network. Data persisted via named volumes.

---

## 7. Implementation Phases

### Phase 1 — Infrastructure (docker-compose + storage clients)
Files: `docker-compose.yml`, `storage/postgres_store.py`, `storage/milvus_store.py`, `storage/neo4j_store.py`

Deliverable: `docker-compose up` brings up all services; storage clients can connect and run schema DDL.

PostgreSQL DDL creates 4 tables. Milvus creates one collection with `dim=768`, `metric_type=COSINE`,
`index_type=IVF_FLAT`. Neo4j creates constraints on `Course.id`.

### Phase 2 — Ingestion Pipeline
Files: `pipeline/chunker.py`, `pipeline/keyphrase.py`, `pipeline/encoder.py`, `pipeline/seed.py`

**Chunking strategy for mechse_syllabi.json:**
Each course produces chunks as follows:
1. One chunk per topic string + its definition (if exists): `"{topic}: {definition_entry}"`
2. If no definition: `"{course_name} [SEP] {topic}"`
3. One chunk for the course description + objectives (split at 512 tokens if long)

**KeyBERT:** Run on each chunk's raw text. Extracts 3-5 n-gram keyphrases (1-2 grams).
These augment the term corpus but are NOT the primary input to the LM (raw tokens are).

**SciNCL encoding:** Feed `"{course_name} [SEP] {chunk_text}"` through `malteos/scincl`.
Output: `numpy.float32` array of shape `(768,)`. Model is loaded once per process and cached.

**seed.py:** Iterates all 33 courses → chunks → embeds → inserts into Milvus + PostgreSQL.
Also builds term count table in PostgreSQL.

### Phase 3 — Scoring Layer
Files: `scoring/language_model.py`, `scoring/jsd.py`, `scoring/vector_similarity.py`,
       `scoring/driving_terms.py`, `scoring/hybrid_scorer.py`

`language_model.py`:
- Reads `term_counts` from PostgreSQL for all courses
- Builds corpus-level `P(w|C)`
- Returns `P(w|d)` dict per course using Dirichlet smoothing

`jsd.py`:
- Takes two smoothed LM dicts
- Computes JSD over union vocabulary
- Returns `lex_sim ∈ [0, 1]`

`vector_similarity.py`:
- For course A: fetch all chunk IDs from PostgreSQL
- For each chunk vector, query Milvus with filter `course_id != A.id AND course_id == B.id`
- Returns symmetrized `sem_sim ∈ [0, 1]`

`hybrid_scorer.py`:
- Runs all N*(N-1)/2 course pairs (528 pairs for 33 courses)
- Writes results to `similarity_cache` in PostgreSQL
- Writes edges to Neo4j (filtered by `MIN_SCORE` threshold)

### Phase 4 — Neo4j Graph + Algorithms
Files: `storage/neo4j_store.py`, `scripts/build_graph.py`

After all edges are stored, run via Neo4j GDS:
```cypher
CALL gds.louvain.write('courseGraph', { writeProperty: 'community' })
CALL gds.pageRank.write('courseGraph', { writeProperty: 'pagerank' })
```

These write `community` and `pagerank` properties back to Course nodes in Neo4j.

### Phase 5 — FastAPI
Files: `api/main.py`, `api/routes/*.py`

Key endpoints:

`GET /similarity?a=ME410&b=ME310`
→ Reads from `similarity_cache` in PostgreSQL
→ Returns `{score, lex_score, sem_score, kl_div, driving_terms}`

`GET /neighbors?course=ME410&top=10`
→ Queries Neo4j: `MATCH (a:Course {id:'ME410'})-[r:SIMILAR_TO]-(b) RETURN b, r ORDER BY r.score DESC LIMIT 10`

`GET /path?from=ME101&to=ME410`
→ Queries Neo4j: `MATCH p=shortestPath((a:Course {id:'ME101'})-[:SIMILAR_TO*]-(b:Course {id:'ME410'})) RETURN p`

`GET /communities`
→ Queries Neo4j: `MATCH (c:Course) RETURN c.community, collect(c.id) ORDER BY c.community`

`POST /ingest/pdf`
→ Accepts multipart PDF + `course_id` + `course_name`
→ Runs full pipeline: parse → chunk → embed → store → recompute scores for new course

---

## 8. Environment Variables (`.env`)

```
# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=siip
POSTGRES_USER=siip
POSTGRES_PASSWORD=

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=

# Scoring parameters
ALPHA=0.4               # weight of lex_sim in hybrid score (0-1)
DIRICHLET_MU=2000       # Dirichlet prior for language model smoothing
MIN_SCORE=0.25          # minimum final_sim to store as Neo4j edge
TOP_K_MILVUS=5          # top-k neighbors to retrieve per chunk in Milvus
TOP_K_DRIVING_TERMS=5   # number of driving terms to store per edge

# Model
SCINCL_MODEL=malteos/scincl   # HuggingFace model ID
SCINCL_CACHE_DIR=./.model_cache
```

---

## 9. What the User Fills In

Only the passwords/secrets need to be set. Everything else has working defaults:

| Variable | What to fill |
|----------|-------------|
| `POSTGRES_PASSWORD` | Any password (e.g. `siip_local`) |
| `NEO4J_PASSWORD` | Any password (min 8 chars for Neo4j) |
| Everything else | Already has a working default |

---

## 10. Sequence: First-Time Setup

```
docker-compose up -d                  # 1. Start all services
pip install -r requirements.txt       # 2. Install Python deps
python scripts/seed.py                # 3. Load 33 courses into all stores
python scripts/build_graph.py         # 4. Compute all 528 pairwise scores
uvicorn api.main:app --port 8080      # 5. Start API
```

Open `http://localhost:8080/docs` to see the Swagger UI.
Open `http://localhost:7474` for Neo4j Browser (visual graph).

---

## 11. Limitations & Future Work

- **33 courses only** from `mechse_syllabi.json`. The pipeline supports adding more via PDF upload.
- **SciNCL model download** (~440MB) happens on first `seed.py` run. Subsequent runs use cache.
- **Louvain with 33 nodes** will produce trivially obvious communities. Useful only once >100 courses are loaded.
- **No frontend** — this is a pure API. Connecting to the existing `visualize.html` is future work.
- **Embedding recomputation** — changing `SCINCL_MODEL` requires re-running `seed.py` from scratch.
