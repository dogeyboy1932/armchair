import numpy as np
from storage.milvus_store import get_embeddings_for_course, search_in_course


def sem_sim(course_a_id: str, course_b_id: str) -> float:
    """
    Symmetric semantic similarity via SciNCL embeddings + Milvus ANN.

    For each chunk in A, find its nearest neighbour in B (max cosine score).
    Average across all A-chunks → directed(A→B).
    Symmetrise: 0.5 * directed(A→B) + 0.5 * directed(B→A).

    Returns a value in [0, 1] (negative scores clamped to 0).
    """
    embs_a = get_embeddings_for_course(course_a_id)
    embs_b = get_embeddings_for_course(course_b_id)

    if not embs_a or not embs_b:
        return 0.0

    scores_ab = search_in_course(embs_a, course_b_id, limit=1)
    scores_ba = search_in_course(embs_b, course_a_id, limit=1)

    directed_ab = float(np.mean(np.clip(scores_ab, 0, 1))) if scores_ab else 0.0
    directed_ba = float(np.mean(np.clip(scores_ba, 0, 1))) if scores_ba else 0.0

    return 0.5 * (directed_ab + directed_ba)
