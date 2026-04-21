from fastapi import APIRouter, HTTPException, Query
import storage.postgres_store as pg_store

router = APIRouter()


@router.get("")
def get_similarity(
    a: str = Query(..., description="First course ID, e.g. ME 410"),
    b: str = Query(..., description="Second course ID, e.g. ME 310"),
):
    """
    Returns the pre-computed hybrid similarity between two courses.

    - **final_score**: α·lex_score + (1-α)·sem_score
    - **lex_score**: 1 − JSD(P_A, P_B) normalised to [0,1]  (Dirichlet-smoothed LMs)
    - **sem_score**: symmetrised SciNCL cosine similarity via Milvus
    - **jsd**: raw Jensen-Shannon Divergence (nats)
    - **driving_terms**: top terms explaining the overlap
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
):
    """Top-N most similar courses to the given course."""
    neighbors = pg_store.get_neighbors(course, top)
    if not neighbors:
        raise HTTPException(404, detail=f"No neighbors found for '{course}'")
    return {"course": course, "neighbors": neighbors}
