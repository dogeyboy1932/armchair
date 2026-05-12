"""
Generate LLM explanations for the top non-obvious course connections.

Run from akhil_app/ directory:
    python scripts/explain_connections.py
    python scripts/explain_connections.py --top 50 --min-sem 0.3 --dry-run

Reads top-N pairs by non_obvious_score from PostgreSQL, calls Claude Sonnet
for natural-language explanations, and caches results back in similarity_cache.

Prerequisites: run label_categories.py then build_graph.py first.
Cost estimate: ~50 Sonnet calls ≈ $0.30–0.50 total.
"""
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from pipeline.llm_explainer import explain_connection
from storage import postgres_store as pg_store


def _load_course_topics() -> dict[str, list[str]]:
    """Return {course_id: [topic_text, ...]} from mechse_syllabi.json."""
    with open(config.SYLLABI_PATH) as f:
        data = json.load(f)
    course_topics: dict[str, list[str]] = {}
    for course in data.get("courses", []):
        cid    = course.get("id", "")
        topics = course.get("topics", [])
        if cid and topics:
            course_topics[cid] = [str(t) for t in topics]

    # Also pull from topic_definitions.json keys for courses not in syllabi
    with open(config.DEFINITIONS_PATH) as f:
        defs: dict = json.load(f)
    by_course: dict[str, list[str]] = defaultdict(list)
    for key in defs:
        colon = key.find(":")
        if colon == -1:
            continue
        cid   = key[:colon].strip()
        topic = key[colon + 1:].strip()
        by_course[cid].append(topic)
    for cid, topics in by_course.items():
        if cid not in course_topics:
            course_topics[cid] = topics

    return course_topics


def main():
    parser = argparse.ArgumentParser(description="Generate LLM explanations for non-obvious pairs")
    parser.add_argument("--top",     type=int,   default=50,  help="Number of pairs to explain")
    parser.add_argument("--min-sem", type=float, default=0.3, help="Minimum semantic score filter")
    parser.add_argument("--dry-run", action="store_true",     help="Preview without calling API")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip pairs that already have an explanation")
    args = parser.parse_args()

    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set in .env")
        sys.exit(1)

    pairs = pg_store.get_top_non_obvious(top=args.top, min_sem=args.min_sem)
    if not pairs:
        print("No non-obvious pairs found.")
        print("Ensure you have run: label_categories.py → build_graph.py first.")
        sys.exit(1)

    if args.skip_existing:
        pairs = [p for p in pairs if not p.get("llm_explanation")]
        print(f"After skipping existing: {len(pairs)} pairs to explain.")

    print(f"Generating explanations for {len(pairs)} non-obvious pairs…")

    course_topics = _load_course_topics()

    for idx, pair in enumerate(pairs, 1):
        course_a = pair["course_a"]
        course_b = pair["course_b"]
        non_ob   = pair["non_obvious_score"] or 0.0
        sem      = pair["sem_score"] or 0.0
        cat_jsd  = pair["category_jsd"] or 0.0

        topics_a = course_topics.get(course_a, [])[:5]
        topics_b = course_topics.get(course_b, [])[:5]

        if args.dry_run:
            print(f"  [{idx}/{len(pairs)}] {course_a} ↔ {course_b}  "
                  f"non_obvious={non_ob:.3f}  sem={sem:.3f}  cat_jsd={cat_jsd:.3f}")
            continue

        print(f"  [{idx}/{len(pairs)}] {course_a} ↔ {course_b}  non_obvious={non_ob:.3f}…",
              end=" ", flush=True)
        result = explain_connection(
            course_a=course_a, topics_a=topics_a,
            course_b=course_b, topics_b=topics_b,
            sem_score=sem, cat_jsd=cat_jsd,
        )

        parts = []
        for key, label in [("shared_math","Shared math"), ("why_surprising","Why surprising"), ("analogy","Analogy")]:
            val = result.get(key) or result.get("explanation", "")
            if isinstance(val, dict):
                val = " ".join(str(v) for v in val.values())
            if val:
                parts.append(f"{label}: {val}")
        full_text = "\n".join(parts)
        if full_text:
            pg_store.update_llm_explanation(course_a, course_b, full_text)
            print(f"✓  {full_text[:80]}…")
        else:
            print("(no explanation returned)")

    if not args.dry_run:
        print(f"\nDone — explanations stored for up to {len(pairs)} pairs.")
        print("Restart the API server to serve the new explanations.")


if __name__ == "__main__":
    main()
