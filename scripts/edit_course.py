"""
Serialize / deserialize a single course for manual editing.

1. Set COURSE_ID below to the course you want to edit.
2. Run dump → edit the JSON file → run load.

    python scripts/edit_course.py dump   # DB → data/edit/<course>.json
    python scripts/edit_course.py load   # data/edit/<course>.json → DB
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─────────────────────────────────────────────────────────────────────────────
COURSE_ID = "ME 340"        # ← change this to the course you want to edit
# ─────────────────────────────────────────────────────────────────────────────

import config
from storage.postgres import store as pg_store


def _safe_filename(course_id: str) -> str:
    return course_id.replace(" ", "_").replace("/", "_")


def _get_file_path() -> Path:
    p = Path("data/edit")
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{_safe_filename(COURSE_ID)}.json"


def dump():
    pg_store.init_schema()

    # ── Course metadata ──────────────────────────────────────────────────────
    all_courses = {c[0]: c for c in pg_store.get_all_courses()}
    if COURSE_ID not in all_courses:
        print(f"ERROR: '{COURSE_ID}' not found in DB.")
        print("Available courses:")
        for cid in sorted(all_courses):
            print(f"  {cid}")
        sys.exit(1)

    row = all_courses[COURSE_ID]
    cid, name, description, prereqs, credits, course_type, instructors = row

    # ── Objectives + topic descriptions from chunks ───────────────────────────
    with pg_store._Conn() as cur:
        cur.execute("""
            SELECT chunk_type, raw_text FROM chunks
            WHERE course_id = %s AND chunk_type IN ('objective', 'topic', 'description')
            ORDER BY chunk_id
        """, (COURSE_ID,))
        chunks = cur.fetchall()

    objectives = []
    chunk_topic_descs: dict = {}   # topic_name_lower → description string

    for chunk_type, raw in chunks:
        if chunk_type == 'objective':
            sep = " objectives: "
            block = raw[raw.index(sep) + len(sep):] if sep in raw else raw
            for s in block.replace(";\n", ". ").split(". "):
                s = s.strip().rstrip(".")
                if len(s) > 15:
                    objectives.append(s + ".")

        elif chunk_type == 'topic' and "[SEP]" in raw:
            after = raw[raw.index("[SEP]") + 5:].strip()
            colon = after.find(": ")
            if colon != -1:
                topic_name = after[:colon].strip()
                topic_desc = after[colon + 2:].strip()
                chunk_topic_descs[topic_name.lower()] = topic_desc

        elif chunk_type == 'description':
            colon = raw.find(": ")
            if colon != -1 and not description:
                description = raw[colon + 2:].strip()

    # ── Topic definitions (better descriptions for seeded courses) ────────────
    defs_path = Path(config.DEFINITIONS_PATH)
    topic_defs: dict = {}
    if defs_path.exists():
        with open(defs_path) as f:
            raw_defs = json.load(f)
        for key, val in raw_defs.items():
            colon = key.find(":")
            if colon != -1:
                k_cid   = key[:colon].strip().upper()
                k_topic = key[colon + 1:].strip()
                if k_cid == COURSE_ID.upper():
                    topic_defs[k_topic.lower()] = str(val)

    # ── Topics from topic_categories ─────────────────────────────────────────
    with pg_store._Conn() as cur:
        cur.execute("""
            SELECT topic_text, categories, COALESCE(tags, '[]') AS tags
            FROM topic_categories WHERE course_id = %s
            ORDER BY topic_text
        """, (COURSE_ID,))
        tc_rows = cur.fetchall()

    topics = []
    for topic_text, cats, tags in tc_rows:
        cats_dict = cats if isinstance(cats, dict) else json.loads(cats)
        tag_list  = tags if isinstance(tags, list) else json.loads(tags)

        # Best available description
        desc = (topic_defs.get(topic_text.lower())
                or topic_defs.get(topic_text.strip().lower())
                or chunk_topic_descs.get(topic_text.lower())
                or "")

        # Only show non-trivial category weights
        clean_cats = {k: round(v, 4) for k, v in cats_dict.items() if v > 0.005}

        topics.append({
            "name":        topic_text,
            "description": desc.strip()[:500],
            "categories":  clean_cats,
            "tags":        tag_list,
        })

    data = {
        "course_id":   cid,
        "name":        name,
        "description": description or "",
        "prereqs":     prereqs or "",
        "credits":     credits or 0,
        "course_type": course_type or "",
        "instructors": instructors or "",
        "objectives":  objectives,
        "topics":      topics,
    }

    out_path = _get_file_path()
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"✓ Dumped '{name}' ({cid})")
    print(f"  {len(topics)} topics, {sum(1 for t in topics if t['tags'])} with tags")
    print(f"  → {out_path}")
    print()
    print("Edit the file, then run:  python scripts/edit_course.py load")


def load():
    pg_store.init_schema()

    in_path = _get_file_path()
    if not in_path.exists():
        print(f"ERROR: {in_path} not found. Run dump first.")
        sys.exit(1)

    with open(in_path) as f:
        data = dict(json.load(f))

    course_id = data.get("course_id", COURSE_ID)

    # ── Course metadata ──────────────────────────────────────────────────────
    pg_store.upsert_course(
        course_id,
        data.get("name", course_id),
        data.get("description", ""),
        data.get("prereqs", ""),
        int(data.get("credits", 0) or 0),
        0,
        data.get("course_type", ""),
        data.get("instructors", ""),
    )

    # ── Topics ────────────────────────────────────────────────────────────────
    topics_updated = 0
    defs_updated: dict = {}

    for t in data.get("topics", []):
        name  = t.get("name", "").strip()
        if not name:
            continue
        cats  = t.get("categories", {})
        tags  = t.get("tags", [])
        desc  = t.get("description", "").strip()

        pg_store.upsert_topic_category(course_id, name, cats, tags)
        topics_updated += 1

        if desc:
            defs_updated[f"{course_id}: {name}"] = desc

    # ── Persist description edits to topic_definitions.json ──────────────────
    if defs_updated:
        defs_path = Path(config.DEFINITIONS_PATH)
        existing: dict = {}
        if defs_path.exists():
            with open(defs_path) as f:
                existing = json.load(f)
        existing.update(defs_updated)
        with open(defs_path, "w") as f:
            json.dump(existing, f, indent=2)

    print(f"✓ Loaded '{data.get('name', course_id)}' ({course_id})")
    print(f"  {topics_updated} topics updated (categories + tags)")
    if defs_updated:
        print(f"  {len(defs_updated)} descriptions written to topic_definitions.json")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("dump", "load"):
        print("Usage:")
        print("  python scripts/edit_course.py dump   # export to JSON")
        print("  python scripts/edit_course.py load   # import from JSON")
        print()
        print(f"Current COURSE_ID = {COURSE_ID!r}")
        sys.exit(1)

    if sys.argv[1] == "dump":
        dump()
    else:
        load()


if __name__ == "__main__":
    main()
