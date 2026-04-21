"""
Wipe all stores and optionally re-seed from scratch.
Run from the akhil_app/ directory:
    python scripts/reset.py          # wipe only
    python scripts/reset.py --reseed # wipe then re-seed + rebuild graph
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage import postgres_store as pg_store
from storage import milvus_store   as milvus
from storage import neo4j_store    as neo4j


def main():
    print("Dropping PostgreSQL tables …")
    pg_store.drop_all()

    print("Dropping Milvus collection …")
    milvus.drop_collection()

    print("Clearing Neo4j graph …")
    neo4j.clear()

    print("Reset complete.")

    if '--reseed' in sys.argv:
        print("\nRe-seeding …")
        import importlib, scripts.seed as seed_mod
        importlib.reload(seed_mod)
        seed_mod.main()

        print("\nRebuilding graph …")
        import scripts.build_graph as bg_mod
        importlib.reload(bg_mod)
        bg_mod.main()


if __name__ == '__main__':
    main()
