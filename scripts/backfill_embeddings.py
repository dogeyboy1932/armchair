"""
Backfill embeddings for labeled topics that have no chunk in Milvus.

For every topic in topic_categories that lacks a matching chunk in the chunks
table, this script creates the chunk text, embeds it with SciNCL, inserts it
into PostgreSQL and Milvus, then re-runs build_topic_graph for affected courses.

Run from akhil_app/:
    python scripts/backfill_embeddings.py
    python scripts/backfill_embeddings.py --dry-run   # preview only, no writes
    python scripts/backfill_embeddings.py --course "MATH 231"
"""
import sys
import json
import argparse
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.postgres import store as pg_store
from storage.vectors import store as milvus
from storage.vectors.encoder import encode

_TOPIC_DEFS_PATH = Path(__file__).parent.parent / "data" / "topic_definitions.json"


def _safe_id(s: str) -> str:
    return s.replace(' ', '_').replace('/', '_')


def _chunk_id_for(course_id: str, topic_text: str) -> str:
    h = hashlib.md5(topic_text.lower().encode()).hexdigest()[:8]
    return f"{_safe_id(course_id)}__topicpatch__{h}"


def _build_chunk_to_topic_index(course_id: str) -> dict[str, str]:
    """Returns {chunk_id: topic_text} for existing chunks of this course."""
    chunks = pg_store.get_chunks_for_course(course_id)
    index: dict[str, str] = {}
    for chunk_id, raw_text in chunks:
        if '[SEP]' not in raw_text:
            continue
        after_sep = raw_text.split('[SEP]', 1)[1].strip().lower()
        index[chunk_id] = after_sep
    return index


def find_missing(course_id: str) -> list[str]:
    """Return topic_texts that are labeled but have no chunk embedding."""
    topic_texts = pg_store.get_topic_texts_for_course(course_id, limit=500)
    if not topic_texts:
        return []

    existing = _build_chunk_to_topic_index(course_id)
    existing_lowers = set(existing.values())

    missing = []
    for topic_text in topic_texts:
        tl = topic_text.lower()
        # Matches if chunk after-SEP is exactly the topic or starts with "topic: "
        matched = any(
            ex == tl or ex.startswith(tl + ':')
            for ex in existing_lowers
        )
        if not matched:
            missing.append(topic_text)
    return missing


def backfill_course(course_id: str, course_name: str, topic_defs: dict,
                    dry_run: bool) -> int:
    missing = find_missing(course_id)
    if not missing:
        print(f"  [{course_id}] all topics already embedded — skipping")
        return 0

    print(f"  [{course_id}] {len(missing)} topics missing embeddings:")
    chunks_pg = []
    chunks_milvus = []

    for topic_text in missing:
        definition = topic_defs.get(f"{course_id}: {topic_text}", '')
        raw_text = (f"{course_name} [SEP] {topic_text}: {definition}"
                    if definition else f"{course_name} [SEP] {topic_text}")
        chunk_id = _chunk_id_for(course_id, topic_text)
        print(f"    + {repr(topic_text[:60])}")
        chunks_pg.append((chunk_id, course_id, 'topic', raw_text, '[]'))
        chunks_milvus.append({'chunk_id': chunk_id, 'course_id': course_id,
                               'raw_text': raw_text})

    if dry_run:
        print(f"    [dry-run] would insert {len(chunks_pg)} chunks")
        return len(chunks_pg)

    # Embed and insert
    raw_texts = [c['raw_text'] for c in chunks_milvus]
    embeddings = encode(raw_texts)

    pg_store.upsert_chunks(chunks_pg)
    milvus.insert_chunks([
        {'chunk_id': chunks_milvus[i]['chunk_id'],
         'course_id': course_id,
         'embedding': embeddings[i]}
        for i in range(len(chunks_milvus))
    ])
    print(f"    ✓ {len(chunks_pg)} chunks embedded and stored")
    return len(chunks_pg)


def main():
    parser = argparse.ArgumentParser(description="Backfill missing topic embeddings")
    parser.add_argument('--dry-run', action='store_true', help="Preview only, no writes")
    parser.add_argument('--course', type=str, default=None, help="Process one course only")
    args = parser.parse_args()

    pg_store.init_schema()

    topic_defs: dict = {}
    if _TOPIC_DEFS_PATH.exists():
        topic_defs = json.loads(_TOPIC_DEFS_PATH.read_text())

    # Load course names
    all_courses = {cid: name for cid, name, *_ in pg_store.get_all_courses()}

    if args.course:
        course_ids = [args.course]
    else:
        course_ids = list(pg_store.get_all_term_counts().keys())

    total = 0
    affected = []
    print(f"Scanning {len(course_ids)} courses for missing embeddings…\n")
    for cid in sorted(course_ids):
        course_name = all_courses.get(cid, cid)
        n = backfill_course(cid, course_name, topic_defs, dry_run=args.dry_run)
        if n > 0:
            total += n
            affected.append(cid)

    print(f"\n{'[dry-run] ' if args.dry_run else ''}Done — {total} chunks "
          f"{'would be ' if args.dry_run else ''}backfilled across {len(affected)} courses.")

    if affected and not args.dry_run:
        print(f"\nRe-running topic graph for affected courses: {affected}")
        from scripts.build_topic_graph import build_for_courses
        build_for_courses(affected, top_k=10, min_score=0.05)


if __name__ == "__main__":
    main()
