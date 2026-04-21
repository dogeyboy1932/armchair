import config


def build_corpus_probs(all_term_counts: dict) -> dict:
    """
    P(w | C) — corpus-level unigram probability over all courses.
    all_term_counts: {course_id: {term: count}}
    """
    total: dict[str, int] = {}
    for counts in all_term_counts.values():
        for term, count in counts.items():
            total[term] = total.get(term, 0) + count
    grand_total = sum(total.values()) or 1
    return {term: count / grand_total for term, count in total.items()}


def build_lm(term_counts: dict, corpus_probs: dict, mu: float | None = None) -> dict:
    """
    Dirichlet-smoothed unigram language model for one course.

        P(w | d) = (c(w,d) + μ · P(w|C)) / (|d| + μ)

    term_counts  : {term: count} for this course
    corpus_probs : {term: P(w|C)}
    mu           : Dirichlet prior (default from config)

    Returns {term: probability} over the full corpus vocabulary.
    """
    if mu is None:
        mu = config.DIRICHLET_MU
    doc_len = sum(term_counts.values()) or 1
    return {
        term: (term_counts.get(term, 0) + mu * pw_c) / (doc_len + mu)
        for term, pw_c in corpus_probs.items()
    }


def build_all_lms(all_term_counts: dict) -> dict:
    """
    Build a Dirichlet-smoothed LM for every course.
    Returns {course_id: {term: probability}}
    """
    corpus_probs = build_corpus_probs(all_term_counts)
    return {
        course_id: build_lm(counts, corpus_probs)
        for course_id, counts in all_term_counts.items()
    }
