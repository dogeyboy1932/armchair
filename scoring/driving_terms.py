import math
from collections import defaultdict
import config


def compute_idf(all_term_counts: dict) -> dict:
    """
    IDF for every term in the corpus.
    idf(w) = log( N / (1 + df(w)) )
    """
    N  = len(all_term_counts)
    df: dict[str, int] = defaultdict(int)
    for counts in all_term_counts.values():
        for term in counts:
            df[term] += 1
    return {term: math.log(N / (1 + freq)) for term, freq in df.items()}


def driving_terms(
    lm_a: dict,
    lm_b: dict,
    idf: dict,
    raw_a: dict | None = None,
    raw_b: dict | None = None,
    top_k: int | None = None,
) -> list[str]:
    """
    Top-k terms that best explain the overlap between two courses.

        score(w) = min(P(w|A), P(w|B)) * IDF(w)

    When raw_a and raw_b (original term-count dicts) are provided, only terms
    that actually appear in BOTH documents are considered.  This prevents
    Dirichlet-smoothed ghost probabilities for absent terms from surfacing
    corpus-level boilerplate (e.g. "energy" appearing in every LM via prior).
    """
    if top_k is None:
        top_k = config.TOP_K_DRIVING_TERMS

    # Only consider terms that genuinely appear in both documents
    if raw_a is not None and raw_b is not None:
        candidates = set(raw_a) & set(raw_b)
    else:
        candidates = set(lm_a) & set(lm_b)

    scores: dict[str, float] = {}
    for term in candidates:
        idf_val = idf.get(term, 0.0)
        if idf_val > 0:
            scores[term] = min(lm_a.get(term, 0.0), lm_b.get(term, 0.0)) * idf_val

    return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]
