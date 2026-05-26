"""
Write all edits from data/courses_dump.json back into the database.

Updates:
  - courses table: name, description, prereqs, credits, course_type, instructors
  - topic_categories: categories and tags for every topic
  - data/topic_definitions.json: topic descriptions (persists descriptions outside DB)

Does NOT re-embed topics or rebuild similarity scores. If you renamed or added topics,
run the full ingest pipeline to get new embeddings.

Run:
    python scripts/load_courses.py
    python scripts/load_courses.py --dry-run
    python scripts/load_courses.py --in data/courses_dump.json
    python scripts/load_courses.py --tags-only    # skip metadata, only update tags
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from storage.postgres import store as pg_store


def main():
    parser = argparse.ArgumentParser(description="Load course data from JSON into DB")
    parser.add_argument("--in",        dest="infile", default="data/courses_dump.json")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--tags-only", action="store_true",
                        help="Skip metadata updates — only write category + tag changes")
    args = parser.parse_args()

    in_path = Path(args.infile)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found. Run dump_courses.py first.")
        sys.exit(1)

    with open(in_path) as f:
        dump: dict = json.load(f)

    pg_store.init_schema()

    # Load current topic_definitions.json so we can merge descriptions back in
    defs_path = Path(config.DEFINITIONS_PATH)
    topic_defs: dict = {}
    if defs_path.exists():
        with open(defs_path) as f:
            topic_defs = json.load(f)

    meta_updated   = 0
    topics_updated = 0
    defs_updated   = 0

    for course_id, course in dump.items():
        # ── Course metadata ─────────────────────────────────────────────────────
        if not args.tags_only:
            name        = course.get("name", course_id)
            description = course.get("description", "")
            prereqs     = course.get("prereqs", "")
            credits     = int(course.get("credits", 0) or 0)
            course_type = course.get("course_type", "")
            instructors = course.get("instructors", "")

            if args.dry_run:
                print(f"[{course_id}] name={name!r}  credits={credits}  type={course_type!r}")
            else:
                pg_store.upsert_course(
                    course_id, name, description, prereqs,
                    credits, 0, course_type, instructors
                )
            meta_updated += 1

        # ── Topics ───────────────────────────────────────────────────────────────
        for t in course.get("topics", []):
            topic_name  = t.get("name", t.get("topic", "")).strip()
            categories  = t.get("categories", {})
            tags        = t.get("tags", [])
            description = t.get("description", "").strip()

            if not topic_name:
                continue

            if args.dry_run:
                print(f"  topic: {topic_name!r}")
                print(f"    tags: {tags}")
            else:
                pg_store.upsert_topic_category(course_id, topic_name, categories, tags)

            # Update topic_definitions.json with any description edits
            def_key = f"{course_id}: {topic_name}"
            if description and not args.dry_run:
                if topic_defs.get(def_key) != description:
                    topic_defs[def_key] = description
                    defs_updated += 1

            topics_updated += 1

    if args.dry_run:
        print(f"\nDRY RUN — would update {meta_updated} courses, {topics_updated} topics")
        return

    # Write updated topic_definitions.json
    if defs_updated > 0:
        with open(defs_path, "w") as f:
            json.dump(topic_defs, f, indent=2)
        print(f"✓ Updated {defs_updated} descriptions in {defs_path}")

    print(f"✓ Updated {meta_updated} courses (metadata)")
    print(f"✓ Updated {topics_updated} topics (categories + tags)")
    print()
    print("Tags are now searchable via /topics/search")
    print("To rebuild similarity scores after major changes:")
    print("  python scripts/build_graph.py")


if __name__ == "__main__":
    main()
