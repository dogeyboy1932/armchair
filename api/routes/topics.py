from fastapi import APIRouter, Query
import storage.postgres_store as pg_store

router = APIRouter()


@router.get("/search")
def search_topics(
    q:   str = Query(..., min_length=2, description="Topic keyword"),
    top: int = Query(40, ge=1, le=100),
):
    """
    Search topics by keyword. Returns matching topics with their LLM-assigned
    category distributions, pairwise course similarities, and semantically
    similar topics from other courses (via pre-computed topic_similarity table).
    """
    matches = pg_store.search_topics(q, top)

    # Attach semantic topic matches from other courses
    for m in matches:
        m['topic_matches'] = pg_store.get_similar_topics(
            m['course_id'], m['topic_text'], limit=6
        )

    # Preserve insertion order while deduplicating course IDs
    seen: set = set()
    courses: list[str] = []
    for m in matches:
        if m['course_id'] not in seen:
            seen.add(m['course_id'])
            courses.append(m['course_id'])

    # Pairwise similarities for every unique course pair in the result set
    pairs: list[dict] = []
    for i, ca in enumerate(courses):
        for cb in courses[i + 1:]:
            sim = pg_store.get_similarity(ca, cb)
            if sim:
                pairs.append(sim)

    return {"query": q, "matches": matches, "courses": courses, "course_pairs": pairs}
