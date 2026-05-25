"""
Compute all pairwise similarity scores and build the Neo4j graph.
Run from the akhil_app/ directory:
    python scripts/build_graph.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scoring.language_model import build_all_lms
from scoring.hybrid_scorer  import score_all_pairs
from storage import postgres_store as pg_store
from storage import neo4j_store    as neo4j


def main():
    print("Loading term counts from PostgreSQL …")
    all_counts = pg_store.get_all_term_counts()
    if not all_counts:
        print("ERROR: No term counts found. Run scripts/seed.py first.")
        sys.exit(1)
    print(f"  {len(all_counts)} courses found.")

    print("Building Dirichlet-smoothed language models …")
    lms = build_all_lms(all_counts)

    edge_count = score_all_pairs(lms, all_counts)

    print("\nRunning community detection (GDS or NetworkX fallback) …")
    try:
        neo4j.run_community_detection()
        print("  Louvain + PageRank: done")
    except Exception as e:
        print(f"  Community detection failed: {e}")

    print(f"\nGraph build complete — {edge_count} edges in Neo4j.")
    print("Start the API: uvicorn api.main:app --port 8080 --reload")


if __name__ == '__main__':
    main()
