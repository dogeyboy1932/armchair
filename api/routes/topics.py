import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Query, Header, HTTPException
from pydantic import BaseModel
import storage.postgres_store as pg_store
import config
from pipeline.llm_explainer import explain_topic_connection

# Load topic descriptions once at import time
_DEFS: dict = {}
_defs_path = Path(config.DEFINITIONS_PATH)
if _defs_path.exists():
    with open(_defs_path) as _f:
        _DEFS = json.load(_f)

router = APIRouter()


class ExplainRequest(BaseModel):
    source_course: str
    source_topic:  str
    target_course: str
    target_topic:  str
    shared_tags:   list[str] = []
    source_tags:   list[str] = []
    target_tags:   list[str] = []
    force:         bool = False


class SignRequest(BaseModel):
    source_course: str
    source_topic:  str
    target_course: str
    target_topic:  str
    signed_by:     str


class SaveTopicExplanationRequest(BaseModel):
    source_course: str
    source_topic:  str
    target_course: str
    target_topic:  str
    explanation:   str


@router.get("/course-info")
def course_info(course: str = Query(..., description="Course ID")):
    """
    Returns full tag summary and topic list for a course — used by the detail panel.
    Tags are aggregated across all topics, sorted by frequency.
    """
    summary = pg_store.get_course_tag_summary(course)

    # Enrich topics with descriptions
    topics_enriched = []
    for t in summary["topics"]:
        key = f"{course}: {t['topic']}"
        topics_enriched.append({
            **t,
            "description": _DEFS.get(key, ""),
        })

    return {
        "course_id": course,
        "tags":      summary["tags"],
        "topics":    topics_enriched,
    }


@router.get("/search")
def search_topics(
    q:   str = Query(..., min_length=2, description="Topic keyword or buzzword"),
    top: int = Query(40, ge=1, le=100),
):
    """
    Two-phase topic search:

    Phase 1 — Direct: topics whose text or tags contain the query string.
    Phase 2 — Related: topics from other courses sharing exact tags with phase-1 hits.

    Example: searching "RLC circuit" matches ECE210's RLC Circuit topic (phase 1),
    then surfaces ME340's Spring-Mass-Damper (phase 2) because both share tags like
    "second-order-ode" and "natural-frequency".
    """
    def _add_description(item: dict) -> dict:
        key = f"{item['course_id']}: {item['topic_text']}"
        item['description'] = _DEFS.get(key, "")
        return item

    # Phase 1: direct text + tag match
    matches = pg_store.search_topics(q, top)

    for m in matches:
        _add_description(m)
        m['topic_matches'] = pg_store.get_similar_topics(
            m['course_id'], m['topic_text'], limit=6
        )

    # Collect all tags from direct matches for phase 2
    all_tags: list[str] = []
    seen_tags: set = set()
    for m in matches:
        for tag in m.get('tags', []):
            if tag not in seen_tags:
                seen_tags.add(tag)
                all_tags.append(tag)

    # Phase 2: other courses sharing tags with phase-1 hits
    direct_courses = list(dict.fromkeys(m['course_id'] for m in matches))
    related = pg_store.find_related_by_tags(all_tags, exclude_courses=direct_courses)

    for r in related:
        _add_description(r)
        r['topic_matches'] = pg_store.get_similar_topics(
            r['course_id'], r['topic_text'], limit=4
        )

    # All unique courses across both phases
    seen: set = set()
    courses: list[str] = []
    for m in matches + related:
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

    # Attach cached explanations to related items
    for r in related:
        r['explanation'] = None
        r['signed_by']   = None

    return {
        "query":        q,
        "matches":      matches,   # direct text/tag hits
        "related":      related,   # cross-domain via shared tags
        "courses":      courses,
        "course_pairs": pairs,
    }


@router.post("/explain")
def explain_topic(
    body: ExplainRequest,
    x_api_key: Optional[str] = Header(None),
):
    """
    Generate (or retrieve cached) LLM explanation for a cross-domain topic pair.
    Pass X-Api-Key header with a Gemini key to generate. Omit to retrieve only cached.
    Pass force=true to regenerate even if a cached explanation exists.
    """
    cached = pg_store.get_topic_explanation(
        body.source_course, body.source_topic,
        body.target_course, body.target_topic,
    )
    if cached and cached.get("explanation") and not body.force:
        return {**cached, "cached": True}

    if not x_api_key:
        if cached:
            return {**cached, "cached": True}
        return {"explanation": None, "signed_by": None, "cached": False}

    # Fetch full context from DB — descriptions, categories, course names
    src_ctx = pg_store.get_topic_context(body.source_course, body.source_topic)
    tgt_ctx = pg_store.get_topic_context(body.target_course, body.target_topic)

    # Descriptions from topic_definitions.json if available
    import json as _json
    from pathlib import Path
    import config as _cfg
    defs: dict = {}
    defs_path = Path(_cfg.DEFINITIONS_PATH)
    if defs_path.exists():
        with open(defs_path) as f:
            defs = _json.load(f)
    src_desc = defs.get(f"{body.source_course}: {body.source_topic}", "") or src_ctx.get("course_description", "")
    tgt_desc = defs.get(f"{body.target_course}: {body.target_topic}", "") or tgt_ctx.get("course_description", "")

    # Use shared_tags from the request, fall back to overlap between both tag lists
    shared = body.shared_tags
    if not shared:
        shared = list(set(src_ctx["tags"]) & set(tgt_ctx["tags"]))

    # Determine if this is a non-obvious connection by category divergence
    def _jsd_cats(c1: dict, c2: dict) -> float:
        import math
        cats = set(c1) | set(c2)
        if not cats:
            return 0.0
        p = [c1.get(k, 0) for k in cats]
        q = [c2.get(k, 0) for k in cats]
        sp, sq = sum(p), sum(q)
        if sp == 0 or sq == 0:
            return 0.0
        p = [x / sp for x in p]
        q = [x / sq for x in q]
        m = [(pi + qi) / 2 for pi, qi in zip(p, q)]
        def _kl(a, b):
            return sum(ai * math.log(ai / bi) for ai, bi in zip(a, b) if ai > 0 and bi > 0)
        return (_kl(p, m) + _kl(q, m)) / 2

    cat_jsd = _jsd_cats(src_ctx.get("categories", {}), tgt_ctx.get("categories", {}))
    is_non_obvious = cat_jsd >= 0.25 or body.source_course != body.target_course

    try:
        from google import genai
        client = genai.Client(api_key=x_api_key)
        result = explain_topic_connection(
            source_course=body.source_course,
            source_topic=body.source_topic,
            target_course=body.target_course,
            target_topic=body.target_topic,
            shared_tags=shared,
            source_tags=src_ctx["tags"],
            target_tags=tgt_ctx["tags"],
            source_description=src_desc,
            target_description=tgt_desc,
            source_categories=src_ctx["categories"],
            target_categories=tgt_ctx["categories"],
            source_course_name=src_ctx.get("course_name"),
            target_course_name=tgt_ctx.get("course_name"),
            is_non_obvious=is_non_obvious,
            client=client,
        )
    except Exception as e:
        raise HTTPException(502, detail=str(e))

    parts = []
    for key, label in [("connection",  "Connection"),
                        ("in_a",        "In " + body.source_course),
                        ("in_b",        "In " + body.target_course),
                        ("surprise",    "Why non-obvious")]:
        val = (result.get(key) or "").strip()
        if val:
            parts.append(f"{label}: {val}")
    explanation = "\n".join(parts)

    signed_by = cached.get("signed_by") if cached else None
    pg_store.upsert_topic_explanation(
        body.source_course, body.source_topic,
        body.target_course, body.target_topic,
        explanation, signed_by,
    )
    return {"explanation": explanation, "signed_by": signed_by, "cached": False}


@router.post("/save-explanation")
def save_topic_explanation(body: SaveTopicExplanationRequest):
    """Save a manually-edited explanation for a topic pair (overwrites LLM-generated)."""
    cached = pg_store.get_topic_explanation(
        body.source_course, body.source_topic,
        body.target_course, body.target_topic,
    )
    signed_by = cached.get("signed_by") if cached else None
    pg_store.upsert_topic_explanation(
        body.source_course, body.source_topic,
        body.target_course, body.target_topic,
        body.explanation, signed_by,
    )
    return {"ok": True}


@router.post("/sign")
def sign_topic_explanation(body: SignRequest):
    """Attach a professor signature to a topic connection explanation."""
    if not body.signed_by.strip():
        raise HTTPException(400, detail="signed_by cannot be empty")
    pg_store.sign_topic_explanation(
        body.source_course, body.source_topic,
        body.target_course, body.target_topic,
        body.signed_by.strip(),
    )
    return {"ok": True, "signed_by": body.signed_by.strip()}
