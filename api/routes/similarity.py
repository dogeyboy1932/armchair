from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional
import storage.postgres_store as pg_store
from scoring.category_scorer import course_category_vector, CATEGORIES
from pipeline.llm_explainer import explain_connection

router = APIRouter()


@router.get("/categories")
def get_course_categories(
    course: str = Query(..., description="Course ID, e.g. ME 340"),
):
    """
    Averaged 8-category probability distribution for a course, computed from
    all its LLM-labeled topics. Use this to understand a course's disciplinary
    composition and compare it to another course's distribution.
    """
    dists = pg_store.get_topic_categories_for_course(course)
    if not dists:
        raise HTTPException(
            404, detail=f"No category data for '{course}'. Run scripts/label_categories.py first."
        )
    vec = course_category_vector(dists)
    return {
        "course_id":   course,
        "topic_count": len(dists),
        "categories":  {cat: round(vec[i], 4) for i, cat in enumerate(CATEGORIES)},
    }


@router.get("")
def get_similarity(
    a: str = Query(..., description="First course ID, e.g. ME 410"),
    b: str = Query(..., description="Second course ID, e.g. ME 310"),
):
    """
    Pre-computed hybrid similarity between two courses.

    - **final_score**: α·lex_score + (1-α)·sem_score
    - **lex_score**: TF-IDF cosine similarity
    - **sem_score**: SciNCL cosine similarity (calibrated)
    - **category_jsd**: Jensen-Shannon divergence between category distributions [0,1]
    - **non_obvious_score**: sem_score × category_jsd — high = non-obvious cross-domain connection
    - **llm_explanation**: Claude-generated explanation (if available)
    """
    result = pg_store.get_similarity(a, b)
    if result is None:
        raise HTTPException(
            404,
            detail=f"No similarity found for '{a}' ↔ '{b}'. "
                   "Run scripts/build_graph.py first.",
        )
    return result


@router.get("/neighbors")
def get_neighbors(
    course: str = Query(..., description="Course ID"),
    top:    int  = Query(10, ge=1, le=50),
    sort:   str  = Query("hybrid", description="Sort by: 'hybrid' or 'non_obvious'"),
):
    """Top-N most similar (or most non-obviously connected) courses."""
    if sort not in ("hybrid", "non_obvious"):
        raise HTTPException(400, detail="sort must be 'hybrid' or 'non_obvious'")
    neighbors = pg_store.get_neighbors(course, top, sort=sort)
    if not neighbors:
        raise HTTPException(404, detail=f"No neighbors found for '{course}'")
    return {"course": course, "neighbors": neighbors, "sort": sort}


@router.get("/non-obvious")
def get_non_obvious(
    top:     int   = Query(20, ge=1, le=200, description="Number of pairs to return"),
    min_sem: float = Query(0.0, ge=0.0, le=1.0, description="Minimum semantic score filter"),
):
    """
    Top non-obvious course connections ranked by non_obvious_score = sem × category_JSD.

    Pairs with high semantic similarity but very different category distributions represent
    cross-domain connections that are structurally similar but not obviously related.
    Requires label_categories.py + build_graph.py to have been run.
    """
    pairs = pg_store.get_top_non_obvious(top=top, min_sem=min_sem)
    if not pairs:
        raise HTTPException(
            404,
            detail="No non-obvious pairs found. Run scripts/label_categories.py "
                   "then scripts/build_graph.py to populate non_obvious_score.",
        )
    return {"pairs": pairs, "count": len(pairs)}


@router.get("/explain")
def get_explanation(
    a: str = Query(..., description="First course ID"),
    b: str = Query(..., description="Second course ID"),
    x_api_key: Optional[str] = Header(None, description="Gemini API key for on-demand generation"),
):
    """
    Return the cached LLM explanation for a course pair.

    If no explanation is cached and `X-Api-Key` is provided, generates one using
    the caller's Gemini API key and caches the result. Without a key, returns an
    empty explanation — the UI shows a 'Generate' button instead.
    """
    result = pg_store.get_similarity(a, b)
    if result is None:
        raise HTTPException(404, detail=f"No similarity record for '{a}' ↔ '{b}'")

    if not result.get("llm_explanation"):
        if not x_api_key:
            # No cached explanation and no key — let the UI show the Generate button
            return {
                "course_a":          result["course_a"],
                "course_b":          result["course_b"],
                "sem_score":         result["sem_score"],
                "category_jsd":      result["category_jsd"],
                "non_obvious_score": result["non_obvious_score"],
                "llm_explanation":   "",
                "generated":         False,
            }

        ca = result["course_a"]
        cb = result["course_b"]
        topics_a = pg_store.get_topic_texts_for_course(ca, limit=5)
        topics_b = pg_store.get_topic_texts_for_course(cb, limit=5)
        try:
            from google import genai
            llm = genai.Client(api_key=x_api_key)
            llm_result = explain_connection(
                course_a=ca, topics_a=topics_a,
                course_b=cb, topics_b=topics_b,
                sem_score=result["sem_score"] or 0.0,
                cat_jsd=result["category_jsd"] or 0.0,
                client=llm,
            )
        except Exception as e:
            raise HTTPException(502, detail=str(e))
        parts = []
        for key, label in [("shared_math", "Shared math"),
                            ("why_surprising", "Why surprising"),
                            ("analogy", "Analogy")]:
            val = llm_result.get(key) or llm_result.get("explanation", "")
            if isinstance(val, dict):
                val = " ".join(str(v) for v in val.values())
            if val:
                parts.append(f"{label}: {val}")
        explanation = "\n".join(parts)
        if explanation:
            pg_store.update_llm_explanation(ca, cb, explanation)
        result["llm_explanation"] = explanation

    return {
        "course_a":          result["course_a"],
        "course_b":          result["course_b"],
        "sem_score":         result["sem_score"],
        "category_jsd":      result["category_jsd"],
        "non_obvious_score": result["non_obvious_score"],
        "llm_explanation":   result["llm_explanation"] or "",
        "generated":         True,
    }
