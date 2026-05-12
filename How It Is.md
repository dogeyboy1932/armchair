# SIIP — How It Is
## Semantic Similarity & Non-Obvious Connection Engine
### UIUC MechSE Curriculum Mapping Project

---

## What This Is

SIIP (Semantic Similarity & Insight Pipeline) is a locally-runnable knowledge base and
similarity engine for UIUC engineering courses. The core problem it solves: standard
similarity engines surface obvious same-domain matches first (ME 340 ↔ ME 310 — both
mechanical systems). SIIP is specifically designed to find the *non-obvious* ones — courses
that are semantically related but come from completely different disciplines (ME 340's
spring-mass system ↔ ECE 206's RLC circuit — both describe second-order damped oscillators,
different domain entirely).

**Research context:** Supervisor Eliot Bethke (bethke2@illinois.edu), UIUC MechSE.
Goal: surface cross-domain connections spanning fluids ↔ mechanics, electronics ↔ materials,
CS ↔ engineering — connections that are structurally similar but not obviously related.

---

## Tech Stack

| Service | Role | Port |
|---------|------|------|
| **FastAPI** | REST API + serves the UI | 8080 |
| **PostgreSQL 15** | Primary relational store — courses, chunks, scores, categories, explanations | 5433 |
| **Milvus 2.3.3** | Vector store — SciNCL 768-dim embeddings for ANN semantic search | 19530 |
| **Neo4j 5.15 (GDS)** | Graph DB — course similarity graph, Louvain communities, PageRank | 7687 |
| **SciNCL** (`malteos/scincl`) | Sentence transformer — encodes academic text to 768-dim vectors | local |
| **Gemini API** | LLM layer — topic extraction, category labeling, connection explanation | remote |

All five services run via Docker Compose. The Python backend runs outside Docker in a `.venv`.

```bash
docker compose up -d     # start PostgreSQL, Milvus, Neo4j
uvicorn api.main:app --port 8080 --reload
```

---

## Data Model

### PostgreSQL Tables

**`courses`** — one row per course
```
course_id (PK)  name  description  prereqs  credits  sequence  course_type  instructors
```

**`chunks`** — text segments extracted from each course
```
chunk_id (PK)  course_id (FK)  chunk_type  raw_text  keyphrases
chunk_type: 'topic' | 'definition' | 'description' | 'objective'
```
Topic and definition chunks are embedded in Milvus. Description/objective chunks
contribute only to term counts, not embeddings.

Chunk format for topic chunks:
```
"Course Name [SEP] Topic Name: LLM-generated one-sentence definition"
```
The LLM definition comes directly from the `analyze_course()` call during ingest —
not from raw syllabus text.

**`term_counts`** — raw token frequencies per course
```
course_id  term  count   (composite PK)
```
Used to build Dirichlet-smoothed language models and TF-IDF vectors.

**`topic_categories`** — LLM-assigned category distributions per topic
```
course_id  topic_text  categories (JSONB)  labeled_at
```
`categories` is a JSON object: `{"Mechanics": 0.6, "Mathematics": 0.3, "Systems": 0.1, ...}`
All 8 values sum to 1.0. Assigned by the LLM in the same call that extracts topics.
Stored per topic, averaged into course-level vectors for scoring.

**`topic_similarity`** — pre-computed topic-to-topic ANN pairs
```
course_a  topic_a  course_b  topic_b  sem_score   (composite PK)
```
Populated by `scripts/build_topic_graph.py`. One row per cross-course topic pair above
the raw-cosine threshold (0.70). Used by the Topics view to show "similar topics in
other courses" for each keyword match.

**`similarity_cache`** — all pairwise scores (one row per unordered course pair)
```
course_a  course_b  final_score  lex_score  sem_score  jsd
driving_terms  category_jsd  non_obvious_score  llm_explanation  computed_at
```
Always stored with `course_a < course_b` (sorted alphabetically). 595 pairs for 35 courses.
No threshold — every pair is stored regardless of score. The `MIN_SCORE` threshold
only controls which pairs become Neo4j edges.

### Milvus Collection: `course_chunks`
- 768-dimensional float32 vectors (SciNCL L2-normalised → cosine = dot product)
- Metadata: `chunk_id`, `course_id`
- Index: FLAT + COSINE (exact search — dataset is small enough)
- Only `topic` and `definition` chunks are embedded

### Neo4j Graph
- **Nodes**: one per course — `(c:Course {id, name, description})`
- **Edges**: `[:SIMILAR {final_score, lex_score, sem_score, non_obvious_score, category_jsd, driving_terms}]`
  - Only pairs with `final_score ≥ MIN_SCORE (0.55)` get an edge — 123 edges currently
- **GDS algorithms run on every graph update**:
  - Louvain community detection → `community` property on each node
  - PageRank → `pagerank` property on each node

---

## Scoring Pipeline

Every course pair gets three independent scores. All are stored in `similarity_cache`.

### 1. Lexical Score (`lex_score`) — TF-IDF Cosine
```
lex_score = cosine(tfidf(A), tfidf(B))
```
- Term counts tokenized from all chunks (domain stopwords removed)
- TF = term_count / doc_length per course
- IDF = log(N / df) across all courses
- Only shared terms contribute (sparse by design)
- Range: [0, 1]

### 2. Semantic Score (`sem_score`) — SciNCL + Milvus
```
raw_sem = 0.5 × directed(A→B) + 0.5 × directed(B→A)
directed(A→B) = mean over all A-chunks of: max cosine(chunk_A, chunks_B)
sem_score = raw_sem   # raw cosine, no floor or calibration
```
SciNCL encodes academic text into 768-dim vectors. Raw cosine is used directly —
no domain-specific floor is applied. Range: [0, 1] (in practice ~0.65–0.90 for
academic text pairs).

### 3. Hybrid Score (`final_score`)
```
final_score = 0.4 × lex_score + 0.6 × sem_score
```
Alpha = 0.4 (configured in `.env`). Semantic dominates because lex is sparse
for short syllabus text.

### 4. Language Model JSD (`jsd`) — Dirichlet-smoothed
```
P(w | d) = (c(w,d) + μ · P(w|C)) / (|d| + μ)       # μ = 2000
jsd = Jensen-Shannon divergence between P(· | A) and P(· | B)
```
Used internally. High JSD = courses use very different vocabulary distributions.
Stored but not the primary ranking signal.

### 5. Category JSD (`category_jsd`) — 8-Bin Engineering Taxonomy
```
category_vec(course) = average of all topic category distributions for that course
category_jsd = JSD(category_vec(A), category_vec(B))    # range [0, 1]
```
The 8 bins: Mechanics | Thermodynamics | Electrical | Fluids | Materials | Mathematics | Chemistry | Systems

Each topic gets its own 8-bin distribution assigned by the LLM (during ingest, as part
of the single `analyze_course()` call). These are averaged into a course-level fingerprint.
High JSD = very different disciplines.

### 6. Non-Obvious Score (`non_obvious_score`)
```
non_obvious_score = sem_score × category_jsd
```
This is the key signal. High only when:
- **sem_score is high** (topics are semantically similar)
- **category_jsd is high** (the courses come from different domains)

A pair with `sem=0.9, cat_jsd=0.9` = jackpot non-obvious connection.
A pair with `sem=0.9, cat_jsd=0.1` = obvious same-domain match.

---

## LLM Layer

**Principle: Math narrows, LLM explains. LLM does not score.**

The LLM has two jobs in this system:

### Job 1 — Full Course Analysis (on new course upload, ONE call)
**File:** `pipeline/topic_extractor.py` → `analyze_course()`
**Model:** `gemini-2.5-flash-lite`
**Input:** raw PDF/TXT text from a syllabus
**Output (single JSON response):**
```json
{
  "description": "2–3 sentence technical summary of the course",
  "objectives": ["Analyze...", "Derive...", "Apply..."],
  "topics": [
    {
      "name": "Topic Name",
      "description": "one technical sentence",
      "categories": {"Mechanics": 0.0, "Thermodynamics": 0.0, ..., "Systems": 0.0}
    }
  ]
}
```
Everything the ingest pipeline needs — topic names, topic definitions, 8-category
distributions, course description, and learning objectives — comes from this single call.
There are no separate calls for extraction vs. labeling. No fallbacks: if the call fails
or returns invalid JSON, ingest stops and the error is surfaced to the UI.

### Job 2 — Connection Explanation (on user demand only)
**File:** `pipeline/llm_explainer.py`
**Model:** `gemini-2.5-flash`
**Input:** course pair + their topic lists + sem_score + category_jsd
**Output:**
```json
{
  "shared_math": "one sentence: the structural/mathematical pattern both share",
  "why_surprising": "one sentence: why this connection is non-obvious",
  "analogy": "one concrete analogy in plain English"
}
```
Formatted and stored as:
```
Shared math: Both courses use differential equations to model...
Why surprising: One is taught in the CS department while...
Analogy: It's like comparing a traffic light algorithm to a thermostat...
```

**Critical design rule:** Explanations are NEVER pre-generated during ingest.
They are generated on-demand when a user clicks "Generate explanation" in the UI,
using the user's own Gemini API key (passed as `X-Api-Key` header). The result
is cached in `similarity_cache.llm_explanation` — subsequent requests are free.

**API key flow:** The Gemini key lives only in the browser (`localStorage`). It is
sent as the `X-Api-Key` header on every request that touches the LLM — including
ingest. The server has no stored key. If the key is missing or invalid, the endpoint
returns an HTTP 400 with the Gemini error message — no silent fallbacks anywhere.

---

## Ingest Pipeline

### New Course (`POST /ingest/pdf` or `POST /ingest/append` with TXT)
Accepts `.pdf` and `.txt` files. Runs as a FastAPI background task (~60 seconds).

**Status tracking:** After submitting, the UI polls `GET /ingest/status/{course_id}`.
The endpoint returns `{status: "running"|"done"|"error", message: "..."}`. On error,
the message contains the actual exception text. Partial data is cleaned up on failure
(courses, chunks, term_counts, topic_categories, similarity rows all deleted).

**Steps in order:**

1. **LLM: Full course analysis** — ONE Gemini call returns description + objectives +
   topics (with definitions and 8-category distributions). No further LLM calls during ingest.
2. **Stack: Chunking** — topics become `"Course Name [SEP] Topic: LLM-definition"` chunks;
   description + objectives become term-count-only chunks (not embedded)
3. **Stack: Embedding** — SciNCL encodes topic chunks → stored in Milvus
4. **Stack: Storage** — course node in PostgreSQL + Neo4j; chunks + term counts in PostgreSQL;
   category distributions in `topic_categories`
5. **Math: Hybrid scoring** — all N−1 pairs scored: `lex`, `sem`, `category_jsd`, `non_obvious`
6. **Stack: Neo4j update** — edges written for pairs above MIN_SCORE (0.55); Louvain + PageRank re-run

After these steps the new course is fully integrated: visible in graph, explorer, topics view,
and non-obvious ranking.

### Append Material to Existing Course (`POST /ingest/append`)
For lecture notes, slides, readings, supplementary PDFs/TXTs. Same background pipeline but:

- Course already exists — no new course node created
- Chunk IDs are timestamped (`CS_521_app1746900000__topic__0`) to avoid collision
- Term counts are **accumulated** (added to existing), not replaced
- New topics extracted + labeled and **upserted** into `topic_categories`
- All similarity scores for this course are **recomputed** from the full combined dataset

### Upload Page (`/upload`)
- Mode toggle: **+ New Course** vs **↑ Append to Existing**
- Accepts `.pdf` and `.txt` files
- API key entered via the `⚙ API Key` nav button — required for upload; 400 returned if missing
- After submit: polls `/ingest/status/{course_id}` every 3 seconds
  - Phase 1 (running): "Ingestion in progress..."
  - Phase 2 (done): waits for course to appear in `/courses` with neighbors, then shows success
  - Error: shows actual error message from the background task

---

## Topic-to-Topic Similarity

Beyond course-level scoring, SIIP pre-computes topic-to-topic semantic similarity
across all courses. This powers the **Topics view** in the UI.

### How it works
1. Every embedded topic chunk has a 768-dim SciNCL vector in Milvus
2. `scripts/build_topic_graph.py` runs `search_global_excluding()` for each topic:
   finds the top-K most similar chunks from *other* courses via ANN
3. Results (raw cosine ≥ 0.70) are stored in `topic_similarity` with both directions
4. Deduplication: highest score kept per unique (course_a, topic_a, course_b, topic_b) pair

### Cost
Pure Milvus ANN — zero LLM calls, zero cost. Runs in ~2–5 minutes for all topics.

```bash
.venv/bin/python scripts/build_topic_graph.py               # all courses
.venv/bin/python scripts/build_topic_graph.py --course "ME 340"   # one course
.venv/bin/python scripts/build_topic_graph.py --top-k 10 --min-score 0.70
```

### UI integration
- **Topics View / keyword search**: each matching topic shows "Similar topics in other courses"
  with `sem_score` and the matching course ID
- **Explorer Details**: clicking a course shows all its topics with dominant category dot + percentage

---

## API Endpoints

### Courses
```
GET  /courses                              → all courses (id, name, description, prereqs, credits, type, instructors)
GET  /courses/{course_id}                  → single course
GET  /courses/{course_id}/topics           → all topics for a course with their 8-category distributions
```

### Similarity
```
GET  /similarity?a=ME 340&b=ECE 205        → full similarity record (all 6 scores + explanation)
GET  /similarity/neighbors?course=ME 340&top=10&sort=hybrid|non_obvious
GET  /similarity/non-obvious?top=20&min_sem=0.3   → top cross-domain pairs ranked by non_obvious_score
GET  /similarity/categories?course=ME 340         → 8-category distribution for a course
GET  /similarity/explain?a=ME 340&b=ECE 205       → cached explanation, or generates with X-Api-Key header
```

### Topics
```
GET  /topics/search?q=vibration&top=40  → keyword search over topic_categories;
                                           returns matching topics + similar topics in other courses
                                           + course-level pair similarities
```

### Graph
```
GET  /graph/all?min_score=0.4           → all nodes + edges for D3 visualization
GET  /graph/path?from=ME 200&to=ME 370  → shortest similarity path between two courses
```

### Ingest
```
POST /ingest/pdf      body: {file (.pdf|.txt), course_id, course_name}  → new course
POST /ingest/append   body: {file (.pdf|.txt), course_id}               → append to existing
GET  /ingest/status/{course_id}   → {status: "running"|"done"|"error", message: "..."}
```

### Meta
```
GET  /health     → {"status": "ok"}
GET  /docs       → FastAPI Swagger UI
```

---

## UI — Three Views + Upload

The frontend is a single vanilla JS + D3.js v7 page (`public/index.html`) with no build step.

### Graph View
- D3 force-directed graph of all courses as nodes, similarity edges above threshold
- Node size = PageRank, node color = Louvain community
- **Normal mode**: edge thickness/opacity by `final_score`
- **Non-obvious mode**: toggle shows edges by `non_obvious_score` (distinct orange color)
- Threshold slider filters edges in real time
- Click a node to highlight its neighborhood

### Explorer View
- Select any course → see its neighbors ranked by hybrid or non-obvious score
- Each neighbor card shows:
  - `final_score` + `non_obvious_score` badges
  - Category distribution bar (8 color-coded bins, percentage labels)
  - Driving terms (top overlapping keywords)
  - Side-by-side category comparison when expanded
  - "Generate explanation" button (or the cached explanation rendered as 3 labeled lines)
- **Details panel** (right sidebar, opens on course selection):
  - Course description, type, credits, prerequisites, instructors
  - Full topic list — each topic shows a color dot for its dominant category + category name + percentage
- "Generate explanation" button requires API key (set via ⚙ nav button)

### Topics View
- Keyword search over all topic texts across all courses
- Left panel: matching topics with their course + category distribution bars
  - Each matching topic expands to show "Similar topics in other courses" (from `topic_similarity`)
    with sem_score and course ID
- Right panel: course-level similarity matrix for courses that share the keyword
- Clicking a matrix cell opens the full course pair detail

### Upload Page (`/upload`)
- Mode toggle: **New Course** vs **Append to Existing**
- Drag-and-drop or click to upload `.pdf` or `.txt` files
- Progress polling with two-phase detection (running → done)
- Error display: if background ingest fails, shows the actual error message
- In append mode: dropdown of all existing courses from `GET /courses`

### API Key Panel
- `⚙ API Key` button in the nav bar
- Slides down a password input — key stored in `localStorage`
- Sent as `X-Api-Key` header on ALL requests that touch the LLM:
  - `/ingest/pdf` and `/ingest/append` (topic extraction + category labeling)
  - `/similarity/explain` (connection explanation)
- Button border turns purple when a key is set
- No key stored server-side — the server never persists or logs it

---

## Offline Scripts

Run from the `akhil_app/` directory using `.venv/bin/python scripts/<name>.py`.

| Script | Purpose |
|--------|---------|
| `scripts/seed.py` | Load 33 courses from `data/mechse_syllabi.json` into all three stores |
| `scripts/build_graph.py` | (Re)compute all N×(N-1)/2 pairs + Neo4j graph |
| `scripts/build_topic_graph.py` | Pre-compute topic-to-topic ANN pairs → `topic_similarity` |
| `scripts/build_topic_graph.py --course "CS 521"` | Rebuild topic pairs for one course |
| `scripts/label_categories.py` | Label topics from `topic_definitions.json` with 8-category distributions |
| `scripts/backfill_embeddings.py` | Find topics with no Milvus embedding and backfill them |
| `scripts/explain_connections.py --top 50 --min-sem 0.3` | Pre-generate LLM explanations for top non-obvious pairs |
| `scripts/reset.py` | Drop all tables and collections (destructive) |

---

## Data Files

| File | Contents |
|------|---------|
| `data/mechse_syllabi.json` | 33 courses: id, name, description, topics[], objectives[] |
| `data/topic_definitions.json` | 1,642 entries: `"COURSE_ID: topic"` → definition string |
| `data/course_info.json` | Course type (Core ME / Elective EM / etc.) + prerequisites |
| `data/instructors.json` | Course → instructor name mappings |

---

## Current Database State (as of May 2026)

| Metric | Count |
|--------|-------|
| Courses | 35 (33 seeded + CS 568 + CS 521 via PDF upload) |
| Chunks | 1,744 |
| Topic category labels | 1,669 topics labeled across all courses |
| Similarity pairs (PostgreSQL) | 595 (35 × 34 / 2) |
| Pairs with `non_obvious_score` | 528 |
| Pairs with cached LLM explanation | 466 |
| Neo4j edges (hybrid ≥ 0.55) | 123 |
| Topic similarity pairs | 6,748 |

---

## Environment Configuration (`.env`)

```
# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=siip
POSTGRES_USER=siip
POSTGRES_PASSWORD=<password>

# Milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<password>

# Scoring
ALPHA=0.4                 # weight of lex vs sem (0.4 lex + 0.6 sem)
DIRICHLET_MU=2000         # language model smoothing prior
MIN_SCORE=0.55            # minimum final_score for a Neo4j edge (raw cosine baseline)
TOP_K_MILVUS=5            # nearest chunks queried per chunk in sem_sim
TOP_K_DRIVING_TERMS=5     # keywords shown per pair

# Models
SCINCL_MODEL=malteos/scincl
SCINCL_CACHE_DIR=./.model_cache
GEMINI_API_KEY=           # leave blank — users supply their key via the UI
CATEGORY_LABEL_MODEL=gemini-2.5-flash-lite
LLM_EXPLAIN_MODEL=gemini-2.5-flash
NON_OBVIOUS_TOP_K=50
```

The Gemini key is never stored server-side. All LLM calls (ingest + explanation) use
the key the user supplies through the browser UI, passed as the `X-Api-Key` header.

---

## Key Design Decisions

**Math scores, LLM explains — never the reverse.**
The LLM has no influence on any score. Scores are deterministic and reproducible.
The LLM only adds the human-readable layer after the math has already ranked pairs.

**One LLM call per course ingest.**
Topic extraction, topic definitions, category labeling, course description, and learning
objectives all come from a single `analyze_course()` call. Fewer calls = fewer failures,
lower cost, faster ingest.

**No silent fallbacks — surface every error.**
If the LLM call fails (bad key, rate limit, invalid JSON), ingest stops, partial data is
cleaned up, and the exact error message is shown in the upload UI. No uniform distributions,
no stub topics, no empty descriptions.

**Raw scoring — no domain-specific calibration.**
`sem_score` is the raw SciNCL cosine value with no floor subtraction. The previous 0.75
floor was MechSE-specific and zeroed out cross-domain pairs (CS ↔ engineering showed 0.0).
Raw cosine preserves all signal for all courses regardless of department.

**Everything is cached, nothing is re-generated without cause.**
Topic category labels: cached permanently. Similarity scores: recomputed only when a
course changes. LLM explanations: generated once on first user request, cached forever.

**Append-not-replace for supplementary material.**
When new material is added to a course, term counts accumulate and new chunks sit alongside
existing ones. A course's profile only ever gets richer, never jumps discontinuously.

**Non-obvious = semantic similarity × category divergence.**
A high hybrid score alone is expected and uninteresting. The interesting signal is when
two courses are semantically similar but come from categorically different domains.
That's the `non_obvious_score`.
