# SIIP Architecture

Single source of truth for system design, file layout, scoring math, APIs, and UI.
For the user-facing "what is this and what can I do with it" pitch see `README.md`.

---

## 1. Context

**Research goal** (supervisor Eliot Bethke, UIUC MechSE): build an engine that
surfaces *non-obvious* cross-domain conceptual overlap across a curriculum.
Standard similarity engines bury those connections under same-domain noise
(every ME course is "similar" to every other ME course). The driving insight
from Bethke: *"semantic similarity on topic:definition strings, weighted by
dissimilarity of category composition."*

That weighting — penalising same-department matches — is what makes the engine
useful. ME 340 ↔ ME 310 is uninteresting (same mechanics curriculum); ME 340 ↔
ECE 206 is interesting (same second-order ODE, different department).

**The two key scores:**

```
final_score        = ALPHA · lex_score + (1 - ALPHA) · sem_score     # ALPHA = 0.4
non_obvious_score  = sem_score × category_jsd
```

`final_score` is the conventional hybrid (lexical + semantic). `non_obvious_score`
is the headline signal: it stays high *only* when topics are semantically close
**and** the courses live in different categorical bins. Same-department pairs
collapse to ~0 on the `category_jsd` term.

**Design principle: math scores, LLM explains — never the reverse.** Scores
are deterministic and reproducible. The LLM (Gemini) is used in exactly two
places: (a) at ingest, one call extracts topics + 8-bin category distribution
per topic; (b) on user demand, one call renders an explanation for a pair the
math has already ranked. The Gemini key lives in the browser's localStorage
and ships as `X-Api-Key`; the server never stores it.

---

## 2. End-to-end walkthrough (a course's journey)

A PDF lands at `POST /ingest/pdf`. Background task, ~60 s:

```
PDF
 │
 ▼
[1] Gemini analyze_course()
    ├── description (2-3 sentences)
    ├── objectives[]
    └── topics[] each with:
        ├── name
        ├── one-sentence definition
        └── 8-bin category distribution {Mechanics, Thermodynamics, Electrical,
            Fluids, Materials, Mathematics, Chemistry, Systems} summing to 1.0
 │
 ▼
[2] Chunker (scoring/chunker.py)
    ├── topic chunks    "Course Name [SEP] Topic: LLM definition"   (embedded)
    ├── definition      same shape, supplementary                    (embedded)
    ├── description     not embedded — term counts only
    └── objectives      not embedded — term counts only
    Also: term_counts {token: count} with domain stopwords removed
 │
 ▼
[3] SciNCL encoder (storage/vectors/encoder.py)
    768-dim float32, L2-normalised (so cosine = dot product)
 │
 ▼
[4] Persistence
    ├── Postgres   courses, chunks, term_counts, topic_categories
    ├── pgvector   chunk_embeddings        (or Milvus locally, via vector_store dispatcher)
    └── Neo4j      (c:Course) node
 │
 ▼
[5] Pairwise scoring (scoring/hybrid_scorer.score_all_pairs)
    For each other course B:
      lex_score      = cosine(tfidf_A, tfidf_B)
      sem_score      = symmetrised SciNCL cosine via ANN
      category_jsd   = JSD(avg category dist A, avg category dist B)
      final_score    = 0.4·lex + 0.6·sem
      non_obvious    = sem · category_jsd
      driving_terms  = min(P(w|A), P(w|B)) · IDF(w)   top 5
    All cached in Postgres similarity_cache (every pair, no threshold).
 │
 ▼
[6] Neo4j graph update
    Pairs with final_score ≥ MIN_SCORE (0.55) → [:SIMILAR] edges
    Louvain (community) + PageRank re-run
      (tries gds.* first, falls back to NetworkX on Aura Free)
 │
 ▼
[7] Topic-to-topic ANN backfill (build_for_courses)
    For each topic chunk: ANN search against chunks of OTHER courses.
    Pairs with raw cosine ≥ 0.70 → topic_similarity table.
 │
 ▼
[8] Cache invalidation
    /topics/search LRU cleared.
```

Result: the new course shows up in every view (Map, Courses, Search Topics)
with neighbours, community color, PageRank-sized node, driving terms, and
ranked non-obvious matches — without any further user action.

**Explanations are separate.** When a user clicks "Generate explanation" on a
pair, `GET /similarity/explain` makes a second Gemini call (using the user's
key) returning `{shared_math, why_surprising, analogy}`. Cached in
`similarity_cache.llm_explanation` forever — first viewer pays, everyone after
gets it free.

---

## 3. Tech stack

| Service | Role | Local port |
|---|---|---|
| FastAPI | REST API + serves the SPA | 8080 |
| PostgreSQL (Supabase) | Courses, chunks, scores, categories, explanations | 5433 |
| pgvector / Milvus | 768-dim SciNCL embeddings | (in-DB) / 19530 |
| Neo4j (Aura, GDS) | Similarity graph, Louvain, PageRank | 7687 |
| SciNCL (`malteos/scincl`) | Sentence transformer | local |
| Gemini | Topic extraction, category labeling, explanations | remote |

Production uses Supabase + Aura. Local dev can either share those (recommended) or run
the legacy isolated stack via `docker compose -f deploy/legacy/docker-compose.yml up`.

---

## 4. Data model

### PostgreSQL

```
courses(course_id PK, name, description, prereqs, credits, sequence, course_type, instructors)

chunks(chunk_id PK, course_id FK, chunk_type, raw_text, keyphrases)
  chunk_type ∈ {topic, definition, description, objective}
  topic+definition chunks are embedded; others contribute term counts only
  topic chunk text format: "Course Name [SEP] Topic: LLM-generated definition"

term_counts(course_id, term, count)   -- composite PK; used for LM + TF-IDF

topic_categories(course_id, topic_text, categories JSONB, labeled_at)
  categories: {"Mechanics": 0.6, "Mathematics": 0.3, ...}  -- sums to 1.0, 8 bins

topic_similarity(course_a, topic_a, course_b, topic_b, sem_score)
  pre-computed topic-to-topic ANN pairs above raw cosine 0.70

similarity_cache(course_a, course_b, final_score, lex_score, sem_score, jsd,
                 driving_terms, category_jsd, non_obvious_score, llm_explanation,
                 computed_at)
  stored with course_a < course_b; every pair, no threshold
```

### Milvus / pgvector — collection `course_chunks`

- 768-dim float32 (SciNCL, L2-normalised so cosine = dot product)
- Metadata: `chunk_id`, `course_id`
- FLAT index, COSINE metric (exact search; dataset small enough)
- Only `topic` and `definition` chunks are embedded

### Neo4j

- Nodes: `(c:Course {id, name, description, community, pagerank})`
- Edges: `[:SIMILAR {final_score, lex_score, sem_score, non_obvious_score, category_jsd, driving_terms}]`
- Edges only created when `final_score ≥ MIN_SCORE` (0.55)
- GDS Louvain + PageRank re-run on every graph update

---

## 5. Scoring pipeline

Every course pair gets these scores, all stored in `similarity_cache`.

### 4.1 Lexical (`lex_score`) — TF-IDF cosine

```
lex_score = cosine(tfidf(A), tfidf(B))
```
Term counts from all chunks with domain stopwords removed. Sparse by design — only
shared terms contribute. Range [0, 1].

### 4.2 Semantic (`sem_score`) — SciNCL + ANN

```
directed(A→B) = mean over A-chunks of: max cosine(chunk_A, chunks_B)
sem_score     = 0.5·directed(A→B) + 0.5·directed(B→A)     # raw cosine, no floor
```
Raw cosine is used directly — no MechSE-specific calibration. (Previously had a 0.75
floor; removed because it zeroed out cross-domain pairs.) Range [0, 1], in practice
0.65–0.90 for academic text.

### 4.3 Hybrid (`final_score`)

```
final_score = ALPHA · lex_score + (1 - ALPHA) · sem_score        # ALPHA = 0.4
```
Semantic dominates because lex is sparse for short syllabus text.

### 4.4 Language-model JSD (`jsd`) — reference only

Dirichlet-smoothed unigram LMs:
```
P(w|d) = (c(w,d) + μ·P(w|C)) / (|d| + μ)        # μ = DIRICHLET_MU = 2000
jsd    = Jensen-Shannon divergence(P(·|A), P(·|B))
```
Stored but not used in ranking. Sum runs over the union vocabulary only.

### 4.5 Category JSD (`category_jsd`)

8 bins: `Mechanics | Thermodynamics | Electrical | Fluids | Materials | Mathematics | Chemistry | Systems`

```
category_vec(course) = mean of topic category distributions for that course
category_jsd         = JSD(category_vec(A), category_vec(B))    # [0, 1]
```
Topic distributions come from the LLM during ingest.

### 4.6 Non-obvious (`non_obvious_score`) — the key signal

```
non_obvious_score = sem_score × category_jsd
```
- `sem=0.9, cat_jsd=0.9` → jackpot cross-domain match
- `sem=0.9, cat_jsd=0.1` → obvious same-department match

### 4.7 Driving terms (explainability)

```
driving_score(w) = min(P(w|A), P(w|B)) · log(N / (1 + df(w)))
```
Only terms in both raw vocabularies count (no smoothing ghosts). Top-5 stored per pair.

---

## 6. LLM layer

**Principle: math narrows, LLM explains. LLM never scores.**

### Job 1 — full course analysis (one call per ingest)
`llm/topic_extractor.py → analyze_course()` using `gemini-2.5-flash-lite`.
Input: raw PDF/TXT. Single JSON response with `description`, `objectives[]`, and
`topics[]` (each with name, definition, and 8-category distribution). No further
LLM calls during ingest.

### Job 2 — connection explanation (on-demand only)
`llm/llm_explainer.py` using `gemini-2.5-flash`. Returns `shared_math`,
`why_surprising`, `analogy`. Cached forever in `similarity_cache.llm_explanation`.

**API key flow:** The Gemini key lives only in the browser (`localStorage`) and is
sent as `X-Api-Key` on every LLM-touching request (ingest + explain). The server
never stores it. Missing key → HTTP 400 with the actual Gemini error. No silent
fallbacks anywhere.

---

## 7. Ingest

### New course — `POST /ingest/pdf` (accepts `.pdf` and `.txt`)

Background task (~60 s):
1. LLM `analyze_course()` — one call, returns everything
2. Chunk topics into `"Course [SEP] Topic: definition"` strings
3. SciNCL encode topic chunks → Milvus / pgvector
4. Upsert course in Postgres + Neo4j; write chunks, term counts, category distributions
5. Score against all N-1 existing courses (lex + sem + category_jsd + non_obvious)
6. Update Neo4j edges (≥ MIN_SCORE) and re-run Louvain + PageRank

UI polls `GET /ingest/status/{course_id}` → `{status, message}`. On error, partial data
is cleaned up automatically.

### Append to existing course — `POST /ingest/append`

For lecture notes, slides, readings. Same pipeline but:
- No new course node created
- Chunk IDs are timestamped to avoid collision (`CS_521_app1746900000__topic__0`)
- Term counts **accumulate** (added, not replaced)
- New topics extracted and **upserted** into `topic_categories`
- All similarity scores for this course are recomputed from the full combined dataset

---

## 8. Topic-to-topic similarity

Powers the Topics view. `scripts/build_topic_graph.py` runs an ANN search for every
topic against all chunks in *other* courses, stores hits with `sem ≥ 0.70` in
`topic_similarity`. Pure Milvus — zero LLM cost. ~2–5 min for the full corpus.

```bash
python scripts/build_topic_graph.py                           # all courses
python scripts/build_topic_graph.py --course "ME 340"         # one course
python scripts/build_topic_graph.py --top-k 10 --min-score 0.70
```

---

## 9. API

### Courses
```
GET /courses
GET /courses/{course_id}
GET /courses/{course_id}/topics      → topics with 8-category distributions
```

### Similarity
```
GET /similarity?a=ME 340&b=ECE 205
GET /similarity/neighbors?course=ME 340&top=10&sort=hybrid|non_obvious
GET /similarity/non-obvious?top=20&min_sem=0.3
GET /similarity/categories?course=ME 340
GET /similarity/explain?a=ME 340&b=ECE 205     # cached, or generates with X-Api-Key
```

### Topics
```
GET /topics/search?q=vibration&top=40
```

### Graph
```
GET /graph/all?min_score=0.4
GET /graph/path?from=ME 200&to=ME 370
```

### Ingest
```
POST /ingest/pdf       body: {file, course_id, course_name}
POST /ingest/append    body: {file, course_id}
GET  /ingest/status/{course_id}
```

### Meta
```
GET /health   → {"status":"ok"}
GET /docs     → Swagger UI
```

---

## 10. UI — single SPA

Vanilla JS + D3.js v7, no build step. All three views live in `ui/index.html`.

### Graph view
D3 force-directed graph. Node size = PageRank, colour = Louvain community.
Toggle Normal/Non-obvious mode swaps edge weights (final_score vs non_obvious_score —
non-obvious mode uses a distinct orange). Threshold slider + click-to-highlight.

### Explorer view
Pick a course → ranked neighbours (by hybrid or non-obvious). Each card shows
`final_score` + `non_obvious_score` badges, 8-bin category distribution bar,
driving terms, and a "Generate explanation" button (cached afterwards). Right
sidebar has full topic list with dominant-category dots.

### Topics view
Keyword search over `topic_categories`. Left: matching topics with
"Similar topics in other courses" expansion (from `topic_similarity`). Right:
course-level similarity matrix for the keyword set.

### Upload page (`/upload`)
Mode toggle: **New Course** vs **Append to Existing**. Drag-and-drop `.pdf`/`.txt`.
Polls `/ingest/status` every 3 s; surfaces real error messages.

### API key panel (⚙)
Password input, stored in `localStorage`. Sent as `X-Api-Key` on all LLM-touching
requests. Button border turns purple when set. Server never sees/persists it.

---

## 11. File layout

Folders are organised by concern: math in `scoring/`, LLM in `llm/`, each storage
backend in its own folder under `storage/`, UI in `ui/`, docs in `docs/`,
sample inputs in `samples/`.

```
akhil_app/
├── README.md, CLAUDE.md            # entry + Claude context
├── config.py                       # ALPHA, DIRICHLET_MU, MIN_SCORE, model IDs (env-overridable)
├── Dockerfile.api                  # Production image (SciNCL + UI + scripts; built by Fly)
├── fly.toml                        # Fly app config (2 GB, always-on, ord)
├── requirements.txt                # Local dev / scripts deps
├── requirements-api.txt            # Production deps (CPU torch, etc.)
│
├── api/                            # FastAPI app
│   ├── main.py                     # lifespan: init schema/collection, mount routers, serve static
│   └── routes/
│       ├── courses.py              # GET /courses, /courses/{id}, /courses/{id}/topics
│       ├── similarity.py           # GET /similarity[/neighbors|/non-obvious|/categories|/explain]
│       ├── topics.py               # GET /topics/search
│       ├── graph.py                # GET /graph/all, /graph/path
│       └── ingest.py               # POST /ingest/{pdf,append}, GET /ingest/status
│
├── scoring/                        # All math + chunker preprocessing
│   ├── chunker.py                  # course dict → (chunks, term_counts); domain stopword filter
│   ├── language_model.py           # Dirichlet-smoothed unigram LMs + corpus prior
│   ├── jsd.py                      # JSD + lex_sim (TF-IDF cosine)
│   ├── vector_similarity.py        # Symmetrised SciNCL cosine via Milvus/pgvector ANN
│   ├── driving_terms.py            # min(P_A,P_B)·IDF over shared raw vocab
│   ├── category_scorer.py          # 8-bin JSD + non_obvious formula
│   └── hybrid_scorer.py            # score_pair / score_all_pairs; writes Postgres + Neo4j
│
├── llm/                            # All Gemini calls
│   ├── topic_extractor.py          # analyze_course() — the only ingest LLM call
│   ├── category_labeler.py         # batch labeling (used by label_categories.py + ingest)
│   └── llm_explainer.py            # connection explanation (on-demand)
│
├── storage/                        # All data stores, one folder per backend
│   ├── postgres/
│   │   └── store.py                # courses, chunks, term_counts, topic_categories, similarity_cache
│   ├── neo4j/
│   │   └── store.py                # Course nodes + SIMILAR edges; Louvain + PageRank
│   └── vectors/                    # Embedding model + vector stores (dispatcher pattern)
│       ├── encoder.py              # SciNCL singleton, L2-normalised (768,) outputs
│       ├── store.py                # Dispatcher: pgvector (prod) or milvus (legacy local)
│       ├── pgvector_store.py       # Supabase chunk_embeddings (production backend)
│       └── milvus_store.py         # Only used with VECTOR_BACKEND=milvus
│
├── ui/                             # Static UI served by FastAPI
│   ├── index.html                  # SPA: Graph + Explorer + Topics views
│   └── upload.html                 # /upload — PDF/TXT ingestion UI
│
├── scripts/                        # Maintenance + edit tooling (see scripts/ section below)
│
├── data/                           # Source JSON + edit buffers
│   ├── mechse_syllabi.json         # 33 courses
│   ├── topic_definitions.json      # 1,642 "COURSE: topic" → definition
│   ├── course_info.json            # type + prereqs
│   ├── instructors.json            # course → instructors
│   ├── courses_dump.json           # Snapshot/edit buffer for dump_courses ↔ load_courses
│   └── edit/                       # Per-course edit buffers from scripts/edit_course.py
│
├── samples/                        # Sample syllabi (test fixtures for the /upload flow)
│
├── docs/                           # Documentation
│   └── ARCHITECTURE.md             # (you are here)
│
├── deploy/
│   ├── free/                       # Supabase + Aura + Fly (production) + CI/CD
│   └── legacy/                     # Local Docker stack + Oracle self-host (quarantined)
│       ├── Dockerfile              # Backend image used by docker-compose.yml
│       ├── docker-compose.yml      # Postgres + Milvus(+etcd+minio) + Neo4j + backend
│       ├── docker-compose.prod.yml # Production overrides for the Oracle path
│       ├── bootstrap.sh            # VPS setup: docker + UFW + seed + caddy (optional TLS)
│       ├── oracle-install.sh       # One-liner curl target for fresh Ubuntu VMs
│       ├── ORACLE.md               # Oracle/VPS self-host docs
│       └── oci/                    # CLI-driven Oracle deploy (00–03 scripts, dormant)
│
└── .model_cache/                   # SciNCL weights (~420 MB), gitignored
```

### scripts/

**Core pipeline (always live):**
- `seed.py` — load 33 courses from `data/mechse_syllabi.json`
- `build_graph.py` — all N(N-1)/2 pairs + Neo4j + Louvain + PageRank
- `build_topic_graph.py` — topic-to-topic ANN → `topic_similarity`
- `label_categories.py` — backfill `topic_categories` via Gemini
- `backfill_embeddings.py` — find topics missing vectors, encode them
- `explain_connections.py` — pre-generate LLM explanations for top non-obvious pairs
- `reset.py` — drop all tables/collections (destructive)

**Manual edit tooling** (DB ↔ JSON round-trip for tweaks):
- `dump_courses.py` + `load_courses.py` — full course dump/restore
- `edit_course.py` — single-course dump/restore via `data/edit/`
- `export_course_tags.py` + `import_course_tags.py` — tag-only round-trip
- `generate_tags.py` — Gemini-driven tag fill for the dump
- `apply_tags.py` — one-time backfill from hardcoded TAGS dict (kept for re-runs)

---

## 12. Environment

```bash
# Postgres (Supabase URL replaces these in production)
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=siip
POSTGRES_USER=siip
POSTGRES_PASSWORD=<password>
DATABASE_URL=                       # if set, supersedes the discrete vars

# Vector backend
VECTOR_BACKEND=pgvector             # or milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530

# Neo4j
NEO4J_URI=bolt://localhost:7687     # or neo4j+s://... for Aura
NEO4J_USER=neo4j
NEO4J_PASSWORD=<password>

# Scoring
ALPHA=0.4                           # weight of lex_score (0.4·lex + 0.6·sem)
DIRICHLET_MU=2000                   # LM smoothing prior
MIN_SCORE=0.55                      # Neo4j edge threshold (raw cosine baseline)
TOP_K_MILVUS=5                      # nearest chunks per chunk in sem_sim
TOP_K_DRIVING_TERMS=5
NON_OBVIOUS_TOP_K=50

# Models
SCINCL_MODEL=malteos/scincl
SCINCL_CACHE_DIR=./.model_cache
GEMINI_API_KEY=                     # blank — users supply via UI
CATEGORY_LABEL_MODEL=gemini-2.5-flash-lite
LLM_EXPLAIN_MODEL=gemini-2.5-flash
```

---

## 13. Current state (May 2026)

| Metric | Count |
|---|---|
| Courses | 35 |
| Chunks | 1,744 |
| Topics labeled | 1,669 |
| Similarity pairs | 595 (35×34/2) |
| Pairs with non_obvious_score | 528 |
| Cached LLM explanations | 466 |
| Neo4j edges (hybrid ≥ 0.55) | 123 |
| Topic similarity pairs | 6,748 |

---

## 14. Design principles

**Math scores, LLM explains — never the reverse.** Scores are deterministic and
reproducible. The LLM only adds the human-readable layer after the math has ranked.

**One LLM call per ingest.** Topic extraction, definitions, category labels,
description, and objectives all come from a single `analyze_course()`.

**No silent fallbacks.** Bad key, rate limit, invalid JSON → ingest stops, partial
data cleaned up, exact error surfaced to the UI.

**Raw scoring — no domain-specific calibration.** No floor subtraction on
`sem_score`. The previous 0.75 floor was MechSE-specific and zeroed cross-domain pairs.

**Cache aggressively.** Topic categories: permanent. Scores: recomputed only on
course change. LLM explanations: generated once, cached forever.

**Append-not-replace** for supplementary material. Term counts accumulate; a course
profile only ever gets richer.

---

## 15. Future work

**Topic-to-topic LLM explanations.** Phase 1 (Milvus topic_similarity) is shipped.
Phase 2 would add on-demand LLM explanations per topic pair (same 3-field format as
course-level), cached forever in a new `topic_similarity.llm_explanation` column.
Cost: ~$0.001/pair, paid once.

**Score refinement via LLM feedback.** Use explanation quality (e.g., "actually not
related") to downweight/upweight raw `sem_score`, stored as a separate
`refined_score` column. Reflects human + LLM judgement over time.

**Topics surfaced inline in Explorer.** Currently topics live in the dedicated
Topics view; embedding them in the Explorer's per-course detail panel would shorten
the path from "this course is interesting" to "here's a related topic in another course."
