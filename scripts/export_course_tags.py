"""
Export all topics from topic_categories to data/course_tags.json.

Includes topic descriptions (from topic_definitions.json) as context so you
know what each topic covers when adding tags. Any existing tags are preserved.

Run:
    python scripts/export_course_tags.py
    python scripts/export_course_tags.py --out data/my_tags.json
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from storage.postgres import store as pg_store


def main():
    parser = argparse.ArgumentParser(description="Export topics to editable JSON")
    parser.add_argument("--out", default="data/course_tags.json",
                        help="Output file (default: data/course_tags.json)")
    args = parser.parse_args()

    pg_store.init_schema()

    # Load descriptions from topic_definitions.json for human-readable context
    defs_path = Path(config.DEFINITIONS_PATH)
    topic_defs: dict = {}
    if defs_path.exists():
        with open(defs_path) as f:
            raw = json.load(f)
        for key, definition in raw.items():
            colon = key.find(":")
            if colon != -1:
                course_id  = key[:colon].strip()
                topic_text = key[colon + 1:].strip()
                topic_defs[(course_id.upper(), topic_text.lower())] = str(definition)[:300]

    # Read all topics from DB
    with pg_store._Conn() as cur:
        cur.execute("""
            SELECT course_id, topic_text, categories, COALESCE(tags, '[]') AS tags
            FROM topic_categories
            ORDER BY course_id, topic_text
        """)
        rows = cur.fetchall()

    if not rows:
        print("No topics found in topic_categories table.")
        print("Run: python scripts/label_categories.py  (or seed the database first)")
        sys.exit(1)

    # Group by course
    courses: dict = {}
    for course_id, topic_text, categories, tags in rows:
        cats = categories if isinstance(categories, dict) else json.loads(categories)
        tag_list = tags if isinstance(tags, list) else json.loads(tags)

        # Top 3 categories for context (skip near-zero ones)
        top_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)
        top_cats = {k: round(v, 3) for k, v in top_cats if v > 0.01}

        # Look up description
        desc = (topic_defs.get((course_id.upper(), topic_text.lower()))
                or topic_defs.get((course_id.upper(), topic_text.upper()))
                or "")

        entry = {
            "topic":       topic_text,
            "description": desc,
            "categories":  top_cats,
            "tags":        tag_list,   # empty [] if not yet generated
        }
        courses.setdefault(course_id, []).append(entry)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(courses, f, indent=2)

    total_topics = sum(len(v) for v in courses.values())
    tagged = sum(1 for topics in courses.values() for t in topics if t["tags"])
    print(f"Exported {total_topics} topics across {len(courses)} courses → {out_path}")
    print(f"Already tagged: {tagged}/{total_topics}")
    print()
    print("Next steps:")
    print("  1. python scripts/generate_tags.py          # LLM auto-fills tags")
    print("  2. (optional) edit data/course_tags.json    # review / tweak")
    print("  3. python scripts/import_course_tags.py     # write to DB")


if __name__ == "__main__":
    main()
