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
    top_k: int | None = None,
) -> list[str]:
    """
    Top-k terms that best explain the overlap between two courses.

        score(w) = min(P(w|A), P(w|B)) * IDF(w)

    Terms that both courses emphasise AND that are distinctive across
    the corpus bubble to the top.
    """
    if top_k is None:
        top_k = config.TOP_K_DRIVING_TERMS

    scores: dict[str, float] = {}
    for term in set(lm_a) & set(lm_b):
        scores[term] = min(lm_a[term], lm_b[term]) * idf.get(term, 0.0)

    return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]
