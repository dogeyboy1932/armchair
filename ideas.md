# SIIP — Tabled Ideas

## Topic-to-Topic Semantic Matching

**Problem**
Current topic search is keyword-only (ILIKE). Searching "Consensus Mechanisms" from CS 521
won't surface "System Stability" from ME 340 even though they're semantically related —
because neither contains the other's keyword. Topics are embedded in Milvus and used to
produce course-level similarity, but the topic-to-topic signal is immediately aggregated away.

**Proposed Architecture**

### Phase 1 — Rough identification (math, no LLM)
- After each course ingestion, run a global Milvus ANN search for each topic chunk
  against all chunks in all OTHER courses (already stored in Milvus)
- Keep top-K (e.g. 5) nearest-neighbor topics per topic, with cosine scores
- Store in a new table `topic_similarity` (course_a, topic_a, course_b, topic_b, sem_score)
- This is O(T × N) Milvus queries where T = topics in new course, N = total chunks
- Feasible at our scale (~1,642 topics, ~5,000 chunks)
- No LLM, no cost — pure vector math

### Phase 2 — Deep explanation (LLM, on-demand, user key)
- When a user clicks "Explain this topic connection", call the LLM with:
  - Topic A name + description
  - Topic B name + description
  - The sem_score from Phase 1
- LLM outputs: shared concept, why surprising, analogy (same 3-field format as course explanations)
- Store explanation in `topic_similarity.llm_explanation`
- Cache permanently — first user pays for it, everyone after gets it free

### Phase 3 — Score refinement (feedback loop)
- LLM explanation quality gives a signal: if the LLM says "actually these aren't related"
  or the explanation is weak, downweight the sem_score
- If very strong match, upweight
- Stored as `topic_similarity.refined_score` (separate from raw sem_score)
- Over time the refined score reflects human + LLM judgement, not just cosine distance

### New API Endpoints
```
GET /topics/similar?topic=Consensus+Mechanisms&course=CS+521&top=10
  → top-K semantically similar topics across all other courses

GET /topics/explain?course_a=CS+521&topic_a=Consensus+Mechanisms
                   &course_b=ME+340&topic_b=System+Stability
  → LLM explanation for this specific topic pair (cached after first call)
```

### UI Changes
- Topics search results show: keyword matches + "Semantically related topics" section
- Each semantic match shows: other course, other topic name, sem_score badge, Explain button
- Explain button passes user's API key → generates and caches explanation inline

### Cost Estimate
- Phase 1: ~0 cost (Milvus queries are free)
- Phase 2: ~$0.001 per explanation, paid once per topic pair, cached forever
- Phase 3: no additional cost (reuses existing LLM output)

### Why tabled
- Not blocking anything today — course-level matching is the primary signal
- Worth building once the topic corpus is large enough (100+ courses) that
  cross-topic discovery becomes the main value proposition
- The `topic_similarity` table can be added via migration without touching existing schema



- Topics for each course should appear in explorer. Should see the related topioc there itself (take me to the topics tab and explore?)
yea,