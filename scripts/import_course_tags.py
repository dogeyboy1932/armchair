"""
Import tags from data/course_tags.json back into the topic_categories table.

Run:
    python scripts/import_course_tags.py
    python scripts/import_course_tags.py --dry-run
    python scripts/import_course_tags.py --in data/course_tags.json
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage import postgres_store as pg_store


def main():
    parser = argparse.ArgumentParser(description="Import tags from JSON into topic_categories")
    parser.add_argument("--in",      dest="infile", default="data/course_tags.json",
                        help="Input JSON (default: data/course_tags.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing to DB")
    args = parser.parse_args()

    in_path = Path(args.infile)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found.")
        sys.exit(1)

    with open(in_path) as f:
        courses: dict = json.load(f)

    pg_store.init_schema()

    total = 0
    tagged = 0
    skipped = 0

    for course_id, topics in sorted(courses.items()):
        for t in topics:
            topic_text = t["topic"]
            tags       = t.get("tags", [])
            categories = t.get("categories", {})
            total += 1

            if not tags:
                skipped += 1
                continue

            if args.dry_run:
                print(f"  [{course_id}] {topic_text}")
                print(f"      tags: {tags}")
            else:
                pg_store.upsert_topic_category(course_id, topic_text, categories, tags)
            tagged += 1

    if args.dry_run:
        print(f"\nDRY RUN — would update {tagged} topics ({skipped} skipped, no tags)")
        return

    print(f"✓ Updated {tagged} topics with tags  ({skipped} skipped — no tags in JSON)")
    print(f"  Total topics in file: {total}")
    print()
    print("Done. Tags are now searchable via /topics/search")


if __name__ == "__main__":
    main()
