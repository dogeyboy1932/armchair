from itertools import combinations
from tqdm import tqdm

import config
from scoring.jsd          import lex_sim  as _lex_sim, jsd as _jsd
from scoring.vector_similarity import sem_sim as _sem_sim
from scoring.driving_terms     import compute_idf, driving_terms as _driving_terms
from storage               import postgres_store as pg_store
from storage               import neo4j_store    as neo4j


def score_pair(
    course_a: str,
    course_b: str,
    lms: dict,
    idf: dict,
) -> dict:
    """
    Compute hybrid similarity for one pair and persist results.

    final_sim = α · lex_sim  +  (1-α) · sem_sim

    Returns a result dict (also written to PostgreSQL + Neo4j if ≥ MIN_SCORE).
    """
    lm_a = lms[course_a]
    lm_b = lms[course_b]

    lex   = _lex_sim(lm_a, lm_b)
    j     = _jsd(lm_a, lm_b)
    sem   = _sem_sim(course_a, course_b)
    final = config.ALPHA * lex + (1 - config.ALPHA) * sem
    terms = _driving_terms(lm_a, lm_b, idf)

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
        result = score_pair(course_a, course_b, lms, idf)
        if result['final'] >= config.MIN_SCORE:
            edge_count += 1

    print(f"Done — {edge_count} Neo4j edges written (threshold={config.MIN_SCORE})")
    return edge_count
