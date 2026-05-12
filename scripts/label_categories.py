"""
Label all topics with engineering category distributions using Gemini Flash.

Run from akhil_app/ directory:
    python scripts/label_categories.py
    python scripts/label_categories.py --dry-run
    python scripts/label_categories.py --batch-size 30

    # Also label courses ingested via PDF (not in topic_definitions.json):
    python scripts/label_categories.py --from-db
    python scripts/label_categories.py --from-db --course "CS 521"

Reads topic_definitions.json (~1,642 entries), calls the Gemini API in batches,
and stores results in the topic_categories PostgreSQL table.

For PDF-ingested courses (--from-db), extracts bullet-point topics from chunk text
and labels each one, so those courses also get non_obvious_score coverage.

Cost estimate: ~1,642 Haiku calls ≈ $0.05–0.10 total.
"""
import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from pipeline.category_labeler import label_topics_batch
from storage import postgres_store as pg_store

# Boilerplate lines to skip when extracting topics from chunks
_SKIP_PATTERNS = re.compile(
    r'(Spring|Fall|Summer|Winter)\s+20\d\d'
    r'|^\s*CS\s+\d+'
    r'|University of Illinois'
    r'|Reading Day|Commencement|Examination'
    r'|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
    r'|Mon|Tue|Wed|Thu|Fri|Sat|Sun'
    r'|^\s*\d+\s*$'
    r'|Grainger College'
    r'|UIUC'
    r'|syllabus|office hours|grading|policy|attendance|academic integrity'
    r'|lecture notes|homework|quiz|exam|midterm|final'
    r'|presentation|coding project|pair project|git repository|commit history'
    r'|demo|submission|due date|week \d|captions|auto-generated'
    r'|students|instructor will|course has|course run',
    re.IGNORECASE,
)

def _is_prose_fragment(line: str) -> bool:
    """True for cut-off sentences that are logistics text, not topic names."""
    # Ends with comma or mid-sentence punctuation (continuation fragment)
    if line.endswith(',') or line.endswith('(auto-') or line.endswith('(see'):
        return True
    # Starts with prose connectors
    if re.match(r'^(Each|The|All|A |An |These|This|Both|Some|Most|In )', line):
        return True
    return False


def _extract_topics_from_chunks(course_id: str) -> list[tuple[str, str, str]]:
    """
    Pull chunk text for a DB-ingested course and extract meaningful topic strings.
    Returns (course_id, topic_text, definition) tuples.
    """
    chunks = pg_store.get_chunks_for_course(course_id)
    full_text = ""
    for _, raw in chunks:
        after_sep = raw.split('[SEP]')[-1].strip() if '[SEP]' in raw else raw
        full_text += after_sep + "\n"

    topics: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    # 1. Bullet-point items — these are usually the actual lecture topics
    for line in full_text.splitlines():
        line = line.strip()
        if line.startswith('•') or line.startswith('-') or line.startswith('*'):
            topic = line.lstrip('•-* ').strip()
            if (10 < len(topic) < 150 and topic not in seen
                    and not _SKIP_PATTERNS.search(topic)
                    and not _is_prose_fragment(topic)):
                seen.add(topic)
                topics.append((course_id, topic, topic))

    # 2. Short standalone lines (headers / named concepts) — skip if no bullets found
    if not topics:
        for line in full_text.splitlines():
            line = line.strip()
            if 15 < len(line) < 120 and line not in seen and not _SKIP_PATTERNS.search(line):
                # Avoid lines that are obviously prose (contain lots of lowercase words)
                words = line.split()
                capitalized = sum(1 for w in words if w[0].isupper()) if words else 0
                if len(words) <= 8 or capitalized / len(words) >= 0.4:
                    seen.add(line)
                    topics.append((course_id, line, line))

    # 3. Fallback: use the full description as one synthetic topic
    if not topics:
        desc = full_text[:600].strip()
        if desc:
            topics.append((course_id, f"{course_id} overview", desc))

    return topics


def _unlabeled_db_courses() -> list[str]:
    """Return course IDs that have chunks but zero entries in topic_categories."""
    pg_store.init_schema()
    with pg_store._Conn() as cur:
        cur.execute("""
            SELECT DISTINCT c.course_id
            FROM chunks c
            WHERE NOT EXISTS (
                SELECT 1 FROM topic_categories tc WHERE tc.course_id = c.course_id
            )
        """)
        return [r[0] for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Label topics with category distributions")
    parser.add_argument("--dry-run",       action="store_true", help="Preview without calling API")
    parser.add_argument("--batch-size",    type=int, default=50, help="Topics per batch (default 50)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip topics already in topic_categories table")
    parser.add_argument("--from-db",       action="store_true",
                        help="Also label courses ingested via PDF (not in topic_definitions.json)")
    parser.add_argument("--course",        type=str, default=None,
                        help="With --from-db: target a single course ID (e.g. 'CS 521')")
    args = parser.parse_args()

    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set in .env")
        sys.exit(1)

    pg_store.init_schema()

    # ── Mode: label DB-ingested (PDF) courses ──────────────────────────────────
    if args.from_db:
        if args.course:
            target_courses = [args.course]
        else:
            target_courses = _unlabeled_db_courses()
            print(f"Found {len(target_courses)} unlabeled DB courses: {target_courses}")

        all_topics: list[tuple[str, str, str]] = []
        for cid in target_courses:
            extracted = _extract_topics_from_chunks(cid)
            print(f"  [{cid}] extracted {len(extracted)} topics from chunks")
            all_topics.extend(extracted)

        if args.dry_run:
            print("\n--- DRY RUN ---")
            for course_id, topic_text, definition in all_topics:
                print(f"  [{course_id}] {topic_text}")
            print(f"\nWould make {len(all_topics)} API calls.")
            return

        if args.skip_existing:
            with pg_store._Conn() as cur:
                cur.execute("SELECT course_id, topic_text FROM topic_categories")
                existing = {(r[0], r[1]) for r in cur.fetchall()}
            all_topics = [(c, t, d) for c, t, d in all_topics if (c, t) not in existing]
            print(f"After skip-existing: {len(all_topics)} remaining.")

        total_labeled = 0
        for i in range(0, len(all_topics), args.batch_size):
            batch = all_topics[i:i + args.batch_size]
            results = label_topics_batch(batch)
            for r in results:
                pg_store.upsert_topic_category(r["course_id"], r["topic_text"], r["categories"])
            total_labeled += len(results)
            print(f"  ✓ {len(results)} stored  (total: {total_labeled})")

        print(f"\nDone — {total_labeled} topics labeled.")
        print("Next: python scripts/build_graph.py  (recomputes non_obvious_score)")
        return

    # ── Default mode: label from topic_definitions.json ───────────────────────
    with open(config.DEFINITIONS_PATH) as f:
        topic_defs: dict = json.load(f)

    all_topics = []
    for key, definition in topic_defs.items():
        colon = key.find(":")
        if colon == -1:
            continue
        course_id  = key[:colon].strip()
        topic_text = key[colon + 1:].strip()
        all_topics.append((course_id, topic_text, str(definition)))

    print(f"Total topics to label: {len(all_topics)}")

    if args.dry_run:
        print("\n--- DRY RUN: first 5 topics ---")
        for course_id, topic_text, definition in all_topics[:5]:
            print(f"  [{course_id}] {topic_text}")
            print(f"      def: {str(definition)[:120]}…")
        print(f"\nWould make ~{len(all_topics)} API calls in "
              f"{(len(all_topics) + args.batch_size - 1) // args.batch_size} batches.")
        return

    if args.skip_existing:
        with pg_store._Conn() as cur:
            cur.execute("SELECT course_id, topic_text FROM topic_categories")
            existing = {(r[0], r[1]) for r in cur.fetchall()}
        all_topics = [(c, t, d) for c, t, d in all_topics if (c, t) not in existing]
        print(f"Skipping {len(existing)} already-labeled topics → {len(all_topics)} remaining.")

    total_labeled = 0
    batch_count   = (len(all_topics) + args.batch_size - 1) // args.batch_size

    for i in range(0, len(all_topics), args.batch_size):
        batch = all_topics[i:i + args.batch_size]
        batch_num = i // args.batch_size + 1
        print(f"Batch {batch_num}/{batch_count} "
              f"(topics {i + 1}–{min(i + args.batch_size, len(all_topics))})…", flush=True)

        results = label_topics_batch(batch)
        for r in results:
            pg_store.upsert_topic_category(r["course_id"], r["topic_text"], r["categories"])

        total_labeled += len(results)
        print(f"  ✓ {len(results)} stored  (total so far: {total_labeled})")

    print(f"\nDone — {total_labeled} topics labeled and stored in topic_categories.")
    print("Next: python scripts/build_graph.py  (recomputes non_obvious_score for all pairs)")


if __name__ == "__main__":
    main()
