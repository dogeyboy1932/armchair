import numpy as np
from scipy.special import rel_entr


def jsd(p: dict, q: dict) -> float:
    """
    Jensen-Shannon Divergence (nats) between two probability dicts.

        M   = 0.5 * (P + Q)
        JSD = 0.5 * KL(P||M) + 0.5 * KL(Q||M)

    Result is in [0, ln(2)] ≈ [0, 0.693].
    Uses the union vocabulary; missing terms default to 0.
    """
    vocab  = list(set(p) | set(q))
    p_vec  = np.array([p.get(w, 0.0) for w in vocab], dtype=np.float64)
    q_vec  = np.array([q.get(w, 0.0) for w in vocab], dtype=np.float64)
    m_vec  = 0.5 * (p_vec + q_vec)

    # rel_entr(a, b) = a·log(a/b)  if a > 0 else 0  (scipy handles this)
    kl_pm = np.sum(rel_entr(p_vec, m_vec))
    kl_qm = np.sum(rel_entr(q_vec, m_vec))
    return float(0.5 * (kl_pm + kl_qm))


def lex_sim(p: dict, q: dict) -> float:
    """
    Lexical similarity in [0, 1] derived from JSD.
    1 = identical term distributions, 0 = maximally divergent.
    """
    return float(1.0 - jsd(p, q) / np.log(2))
