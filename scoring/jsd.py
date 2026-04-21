import math
import numpy as np
from scipy.special import rel_entr


def jsd(p: dict, q: dict) -> float:
    """Jensen-Shannon Divergence (nats) in [0, ln(2)]. Full vocabulary."""
    vocab = list(set(p) | set(q))
    p_vec = np.array([p.get(w, 0.0) for w in vocab], dtype=np.float64)
    q_vec = np.array([q.get(w, 0.0) for w in vocab], dtype=np.float64)
    m_vec = 0.5 * (p_vec + q_vec)
    kl_pm = np.sum(rel_entr(p_vec, m_vec))
    kl_qm = np.sum(rel_entr(q_vec, m_vec))
    return float(0.5 * (kl_pm + kl_qm))


def lex_sim(raw_a: dict, raw_b: dict, idf: dict) -> float:
    """
    TF-IDF cosine similarity between two documents.

    Uses raw term counts (not smoothed LMs) so absent terms contribute
    exactly zero — sparse by design.  IDF naturally down-weights words
    that appear across many courses (e.g. "analysis", "problems") so
    the similarity reflects genuine topical overlap rather than shared
    academic boilerplate.

    Returns a value in [0, 1].
    """
    if not raw_a or not raw_b:
        return 0.0

    len_a = sum(raw_a.values()) or 1
    len_b = sum(raw_b.values()) or 1

    # Build TF-IDF vectors — only over each document's own vocabulary
    def tfidf(raw: dict, total: int) -> dict:
        return {
            w: (cnt / total) * max(idf.get(w, 0.0), 0.0)
            for w, cnt in raw.items()
        }

    vec_a = tfidf(raw_a, len_a)
    vec_b = tfidf(raw_b, len_b)

    # Cosine similarity
    shared = set(vec_a) & set(vec_b)
    dot    = sum(vec_a[w] * vec_b[w] for w in shared)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(min(dot / (norm_a * norm_b), 1.0))
