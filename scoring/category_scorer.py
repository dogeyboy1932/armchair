import math
import numpy as np
from scipy.special import rel_entr

CATEGORIES = [
    "Mechanics",
    "Thermodynamics",
    "Electrical",
    "Fluids",
    "Materials",
    "Mathematics",
    "Chemistry",
    "Systems",
]

_UNIFORM = [1.0 / len(CATEGORIES)] * len(CATEGORIES)


def _jsd_vec(p: list[float], q: list[float]) -> float:
    """JSD between two probability vectors; result in [0, 1] (base-2 log)."""
    p_arr = np.array(p, dtype=np.float64)
    q_arr = np.array(q, dtype=np.float64)
    m = 0.5 * (p_arr + q_arr)
    kl_pm = np.sum(rel_entr(p_arr, m))
    kl_qm = np.sum(rel_entr(q_arr, m))
    return float(min((0.5 * (kl_pm + kl_qm)) / math.log(2), 1.0))


def course_category_vector(topic_dists: list[dict]) -> list[float]:
    """Average category distributions over all topics in a course."""
    if not topic_dists:
        return _UNIFORM[:]
    avg = [0.0] * len(CATEGORIES)
    for dist in topic_dists:
        for i, cat in enumerate(CATEGORIES):
            avg[i] += dist.get(cat, 0.0)
    n = len(topic_dists)
    return [v / n for v in avg]


def compute_category_jsd(vec_a: list[float], vec_b: list[float]) -> float:
    return _jsd_vec(vec_a, vec_b)


def compute_non_obvious(sem_sim: float, cat_jsd: float) -> float:
    """High semantic similarity × high category divergence = non-obvious connection."""
    return float(sem_sim * cat_jsd)
