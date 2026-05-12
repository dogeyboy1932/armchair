# Comprehensive Gameplan: Course Concept Similarity & Semantic Graph Pipeline

## 1. Executive Summary
This project aims to solve the "cross-corpus semantic linking" problem across university syllabi (initially Mechanical Engineering). The goal is to mathematically compute and visually map the conceptual overlap between courses, solving the lexical gap (e.g., identifying that "Fourier's Law" and "Heat Conduction" are tightly linked despite sharing no words).

The system uses a layered architecture: **SciNCL** for domain-aware dense embeddings, **Milvus** for high-dimensional vector similarity search, **CS510 IR Principles** (KL-Divergence and Dirichlet Smoothing) for statistically sound course-to-course scoring and explainability, and **Neo4j** for graph-based knowledge discovery and traversal.

---

## 2. The Tech Stack
* **Data Parsing:** `pdfplumber` or `pymupdf` (extracting raw text from PDFs).
* **Concept Extraction:** `KeyBERT` (extracting explicit n-gram keyphrases from raw text).
* **Embedding Model:** `sentence-transformers` using `malteos/scincl` (768-dimensional vectors trained specifically on scientific/academic text via contrastive learning).
* **Vector Database (Fast Retrieval):** `Milvus` (Standalone via Docker) to handle ANN (Approximate Nearest Neighbor) search at scale.
* **Graph Database (Relational Discovery):** `Neo4j` (Local Docker or AuraDB) to handle transitive mapping, community detection (Louvain), and centrality calculations.
* **Relational Metadata:** `PostgreSQL` to store course IDs, syllabus text, and query logs.
* **Backend/API:** `FastAPI` to serve the search results and similarity scores.
* **Infrastructure:** Local Docker Compose for development (transitioning to AWS EC2/Fargate for production).

---

## 3. Mathematical Foundations & IR Principles

### A. Information Retrieval: Language Model Smoothing
To avoid zero probabilities when comparing course content (where a course lacks a specific term), we apply Dirichlet smoothing to the course's term distribution.

$$P(w|d) = \frac{c(w; d) + \mu P(w|C)}{|d| + \mu}$$

* $c(w; d)$ = count of word $w$ in document (course syllabus) $d$.
* $|d|$ = total length of the document.
* $P(w|C)$ = probability of the word in the entire corpus $C$.
* $\mu$ = Dirichlet prior (tuning parameter).

### B. Similarity Scoring: KL-Divergence
Instead of raw cosine similarity at the macro level, we measure the "distance" between the smoothed probability distributions of two courses. A lower score means higher similarity.

$$D_{KL}(P || Q) = \sum_{x \in X} P(x) \log\left(\frac{P(x)}{Q(x)}\right)$$

* $P(x)$ = Topic/Term distribution of Course A.
* $Q(x)$ = Topic/Term distribution of Course B.

### C. Explainability: Query Likelihood (Vector Space Form)
To explain *why* two courses overlap, we decompose the score to the term level:

$$Score(Course_A, Course_B) = \sum_{terms} \text{tf-idf}(term) \times \text{match\_weight}(term)$$
This allows the UI to output: *"These courses overlap primarily due to shared emphasis on: [Term 1], [Term 2], and [Term 3]."*

---

## 4. Implementation Roadmap

### Phase 1: Ingestion & Granularity (Chunking)
You cannot embed a whole syllabus; the signal dilutes. We break data into Atomic Concept Units.
* **Input:** Raw PDF syllabi.
* **Action:** Parse text, remove boilerplate, and split into weekly modules or thematic bullet points.
* **Output:** Structured JSON schema.
    ```json
    {
      "course_id": "ME_410",
      "course_name": "Heat Transfer",
      "chunk_id": "ME_410_W4",
      "text": "Week 4: Steady-state conduction, thermal resistance networks."
    }
    ```

### Phase 2: Semantic Extraction
Before embedding, extract high-signal keyphrases to reduce noise.
* **Input:** The raw `"text"` string from Phase 1.
* **Action:** Run `KeyBERT` to isolate specific scientific concepts.
* **Output:** Keyphrases appended to the JSON chunk.
    ```json
    {
      "keyphrases": ["steady-state conduction", "thermal resistance", "conduction"]
    }
    ```

### Phase 3: Semantic Encoding (The SciNCL Layer)
Translate text into vector space using a model native to academic jargon.
* **Input:** Concatenated title and abstract/text: `"{course_name} [SEP] {text}"`
* **Action:** Feed through `malteos/scincl`.
* **Output:** A 768-dimensional NumPy array representing the semantic location of that chunk.

### Phase 4: Vector Storage & Nearest Neighbor Search
Store the vectors for sub-millisecond retrieval.
* **Input:** 768-dim vectors + JSON metadata.
* **Action:** Insert into Milvus. Define schema (`embedding_field` with `dim=768`).
* **Output:** An indexed Vector DB.
* **Test:** Query Milvus with "Fluid Dynamics" and verify it returns chunks containing "Bernoulli equation" or "pipe flow" via Cosine Similarity.

### Phase 5: The IR Logic & Explainability Layer
Elevate from chunk-level math to course-level insights.
* **Input:** Pairwise chunk similarities across all courses.
* **Action:** 1. Build unigram language models for each course.
    2. Apply Dirichlet smoothing.
    3. Calculate KL-Divergence between Course A and Course B.
    4. Extract the top driving terms using the Vector Space Model decomposition.
* **Output:** A finalized edge-weight score between two courses, packaged with the terms that justify the score.

### Phase 6: The Knowledge Graph (Neo4j)
Map the ecosystem to discover transitive relationships and prerequisite structures.
* **Input:** Course Metadata (Nodes) and Phase 5 Final Scores (Edges).
* **Action:** 1. Filter out low-similarity noise (e.g., edges below a certain threshold).
    2. Push Nodes and Edges into Neo4j via Cypher queries.
    3. Run Louvain community detection to find major mechanical engineering disciplines naturally clustering.
* **Output:** A queryable graph. (e.g., *"Find the shortest conceptual path from ME 101 to ME 410"*).

### Phase 7: The Final API
Wrap the infrastructure in a clean backend.
* **Input:** User REST request (e.g., `GET /similarity?course_a=ME410&course_b=ME510`).
* **Action:** FastAPI fetches the pre-computed edge weight and explanation terms from PostgreSQL/Neo4j.
* **Output:** ```json
    {
      "course_a": "ME 410",
      "course_b": "ME 510",
      "similarity_score": 0.82,
      "driving_concepts": ["thermal resistance", "fourier analysis"],
      "kl_divergence": 0.14
    }
    ```
