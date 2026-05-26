"""
Semantic similarity via SciNCL embeddings.

Original implementation issued one ANN query per chunk per pair (~100 round-trips
per pair). That's fine over a UNIX socket to local Milvus but catastrophic over
the internet to a managed pgvector. This version:

  1. Fetches each course's embeddings exactly ONCE (process-wide cache).
  2. Computes pairwise cosine similarity as a single numpy matmul.

For 33 courses × ~50 chunks each that's 33 SELECTs total + pure CPU after.
"""
import numpy as np
from storage.vectors.store import get_embeddings_for_course

_cache: dict[str, np.ndarray | None] = {}


def _matrix(course_id: str) -> np.ndarray | None:
    """Return (n_chunks, 768) matrix for a course, or None if no embeddings."""
    if course_id not in _cache:
        embs = get_embeddings_for_course(course_id)
        _cache[course_id] = (
            np.stack(embs).astype(np.float32) if embs else None
        )
    return _cache[course_id]


def sem_sim(course_a_id: str, course_b_id: str) -> float:
    """
    Symmetric semantic similarity via best-match averaging.

    For each chunk in A, find its nearest neighbour in B → mean → directed(A→B).
    Symmetrise: 0.5 * (directed(A→B) + directed(B→A)).

    Embeddings are L2-normalised at encode time, so cosine == dot product.
    Returns a value in [0, 1] (negative scores clamped to 0).
    """
    A = _matrix(course_a_id)
    B = _matrix(course_b_id)

    if A is None or B is None:
        return 0.0

    sims = A @ B.T  # (na, nb) cosine similarities

    scores_ab = sims.max(axis=1)  # best B-match for each A-chunk
    scores_ba = sims.max(axis=0)  # best A-match for each B-chunk

    directed_ab = float(np.mean(np.clip(scores_ab, 0.0, 1.0)))
    directed_ba = float(np.mean(np.clip(scores_ba, 0.0, 1.0)))

    return 0.5 * (directed_ab + directed_ba)


def clear_cache() -> None:
    """Invalidate the in-process embedding cache (e.g. after re-ingest)."""
    _cache.clear()
