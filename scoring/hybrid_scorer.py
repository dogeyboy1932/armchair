from itertools import combinations
from tqdm import tqdm

import config
from scoring.jsd               import lex_sim as _lex_sim, jsd as _jsd
from scoring.vector_similarity import sem_sim as _sem_sim
from scoring.driving_terms     import compute_idf, driving_terms as _driving_terms
from storage                   import postgres_store as pg_store
from storage                   import neo4j_store    as neo4j

# SciNCL cosine similarities for short academic text have a high floor
# (~0.75–0.80) even for unrelated courses.  Subtract this floor and
# re-scale to [0, 1] so the semantic component is actually discriminative.
_SEM_FLOOR = 0.75


def _calibrate_sem(raw: float) -> float:
    return float(max(raw - _SEM_FLOOR, 0.0) / (1.0 - _SEM_FLOOR))


def score_pair(
    course_a: str,
    course_b: str,
    lms: dict,
    idf: dict,
    all_term_counts: dict | None = None,
) -> dict:
    """
    Compute hybrid similarity for one pair and persist results.

    Lexical: TF-IDF cosine similarity (sparse — only actual term overlap).
    Semantic: SciNCL cosine similarity re-scaled above a floor baseline.
    Hybrid:   α · lex + (1-α) · sem
    """
    raw_a = all_term_counts.get(course_a) if all_term_counts else {}
    raw_b = all_term_counts.get(course_b) if all_term_counts else {}
    lm_a  = lms[course_a]
    lm_b  = lms[course_b]

    lex   = _lex_sim(raw_a, raw_b, idf)
    j     = _jsd(lm_a, lm_b)     # stored for reference; not used in hybrid score
    sem   = _calibrate_sem(_sem_sim(course_a, course_b))
    final = config.ALPHA * lex + (1 - config.ALPHA) * sem
    terms = _driving_terms(lm_a, lm_b, idf, raw_a, raw_b)

    pg_store.upsert_similarity(course_a, course_b, final, lex, sem, j, terms)

    if final >= config.MIN_SCORE:
        neo4j.upsert_edge(course_a, course_b, final, lex, sem, j, terms)

    return {'final': final, 'lex': lex, 'sem': sem, 'jsd': j, 'terms': terms}


def score_all_pairs(lms: dict, all_term_counts: dict) -> int:
    """
    Compute and persist similarity for every N*(N-1)/2 course pair.
    Returns the number of Neo4j edges written (score ≥ MIN_SCORE).
    """
    course_ids = list(lms.keys())
    idf        = compute_idf(all_term_counts)
    pairs      = list(combinations(course_ids, 2))
    edge_count = 0

    print(f"Scoring {len(pairs)} pairs across {len(course_ids)} courses …")
    for course_a, course_b in tqdm(pairs, unit="pair"):
        result = score_pair(course_a, course_b, lms, idf, all_term_counts)
        if result['final'] >= config.MIN_SCORE:
            edge_count += 1

    print(f"Done — {edge_count} Neo4j edges written (threshold={config.MIN_SCORE})")
    return edge_count
