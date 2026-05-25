# SIIP — Semantic Similarity & Non-Obvious Connection Engine
## UIUC MechSE Curriculum Mapping Project

### What This Is
A locally-runnable semantic similarity engine for 33 UIUC MechSE courses.
Goal: surface **non-obvious cross-domain connections** between course topics
(e.g., ME340 spring-mass system ↔ ECE210 RLC circuit — same 2nd-order ODE, different domains).

### Quick Start (cloud-backed — same DBs as production)
```bash
cp deploy/free/credentials.env.example deploy/free/credentials.env
# fill DATABASE_URL, NEO4J_URI, NEO4J_PASSWORD
bash deploy/free/link-local-env.sh
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
# ship changes: git push origin main  →  GitHub Actions deploys Fly
```

### Optional isolated local stack (Docker + Milvus)
```bash
docker-compose up -d
python scripts/seed.py
python scripts/build_graph.py
uvicorn api.main:app --port 8080 --reload
```

### Scoring Formula
```
hybrid         = 0.4 × lex_sim + 0.6 × sem_sim
non_obvious    = sem_sim × category_JSD
```
- `lex_sim` = TF-IDF cosine similarity (term overlap)
- `sem_sim` = SciNCL (malteos/scincl) raw cosine similarity — no floor or calibration
- `category_JSD` = Jensen-Shannon divergence between 8-bin category distributions

### 8 Engineering Categories (for topic labeling)
Mechanics | Thermodynamics | Electrical | Fluids | Materials | Mathematics | Chemistry | Systems

### Key Files
- `scoring/hybrid_scorer.py` — main scoring logic (lex + sem + category)
- `scoring/category_scorer.py` — JSD between category distributions + non_obvious formula
- `pipeline/category_labeler.py` — Claude Haiku: assigns category distributions to topics
- `pipeline/llm_explainer.py` — Claude Sonnet: explains non-obvious connections in plain English
- `storage/postgres_store.py` — PostgreSQL: courses, chunks, term_counts, similarity_cache, topic_categories
- `storage/neo4j_store.py` — Neo4j: course graph + Louvain communities + PageRank
- `storage/milvus_store.py` — Milvus: SciNCL 768-dim embeddings (FLAT/COSINE)
- `api/routes/similarity.py` — GET /similarity, /similarity/neighbors, /similarity/non-obvious, /similarity/explain
- `public/index.html` — single SPA with Graph + Explorer views (vanilla JS + D3.js v7)

### API Endpoints
```
GET /courses                              → all 33 courses
GET /similarity?a=ME 340&b=ECE 210        → full similarity record (all scores)
GET /similarity/neighbors?course=ME 340&top=10&sort=hybrid|non_obvious
GET /similarity/non-obvious?top=20&min_sem=0.3  → top cross-domain surprises
GET /similarity/explain?a=ME 340&b=ECE 210      → cached LLM explanation
GET /graph/all?min_score=0.4              → D3 graph data
GET /graph/path?from=ME 200&to=ME 370    → shortest similarity path
POST /ingest/pdf                          → upload new syllabus PDF
```

### Data Files
- `data/mechse_syllabi.json` — 33 courses with topics, definitions, objectives
- `data/topic_definitions.json` — 1,642 enriched definitions ("COURSE: topic" → definition)
- `data/course_info.json` — course types (Core ME / Elective EM / etc.) + prerequisites
- `data/instructors.json` — course → instructor mappings

### Environment (.env)
Cloud-backed local dev (recommended — same Supabase + Aura as production):
```bash
bash deploy/free/link-local-env.sh   # writes .env from deploy/free/credentials.env
```
Or isolated Docker stack: `POSTGRES_HOST=localhost`, `MILVUS_HOST=localhost`, `NEO4J_URI=bolt://localhost:7687`, `VECTOR_BACKEND=milvus`

### Research Context
- Supervisor: Eliot Bethke (bethke2@illinois.edu)
- Goal: non-obvious matches spanning departments (fluids ↔ mechanics, electronics ↔ material science)
- Key insight from email: "semantic similarity on topic:definition strings, weighted by dissimilarity of category composition"
- MechSE_Top50_Results.json (supervisor's category data) not yet received — we generate our own via LLM
- The team wants clean, explained, non-obvious matches they can evaluate without reading score math
