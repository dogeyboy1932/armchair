"""
Seed all 33 courses from mechse_syllabi.json into PostgreSQL, Milvus, and Neo4j.
Run from the akhil_app/ directory:
    python scripts/seed.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tqdm import tqdm
import config
from pipeline.chunker  import chunk_course
from pipeline.encoder  import encode
from storage import postgres_store as pg_store
from storage import milvus_store   as milvus
from storage import neo4j_store    as neo4j


def main():
    # ── Load data files ────────────────────────────────────────────────────────
    print("Loading data files …")
    with open(config.SYLLABI_PATH)     as f: syllabi      = json.load(f)['courses']
    with open(config.DEFINITIONS_PATH) as f: topic_defs   = json.load(f)
    with open(config.COURSE_INFO_PATH) as f: course_info  = json.load(f)
    with open(config.INSTRUCTORS_PATH) as f: instructors  = json.load(f)
    print(f"  {len(syllabi)} courses | {len(topic_defs)} topic definitions")

    # ── Init schemas ───────────────────────────────────────────────────────────
    print("Initialising schemas …")
    pg_store.init_schema()
    neo4j.init_schema()
    milvus.get_or_create_collection()

    # ── Ingest each course ─────────────────────────────────────────────────────
    for course in tqdm(syllabi, desc="Seeding", unit="course"):
        cid  = course['id']
        info = course_info.get(cid, {})

        pg_store.upsert_course(
            course_id   = cid,
            name        = course['name'],
            description = course.get('description', ''),
            prereqs     = (', '.join(course.get('prereq', []))
                           or info.get('prerequisites', '')),
            credits     = course.get('credits', 0),
            sequence    = course.get('sequence', 0),
            course_type = info.get('type', ''),
            instructors = ', '.join(instructors.get(cid, [])),
        )
        neo4j.upsert_course(cid, course['name'], course.get('description', ''))

        chunks, term_counts = chunk_course(course, topic_defs)

        pg_store.upsert_chunks([
            (c['chunk_id'], c['course_id'], c['chunk_type'], c['raw_text'], '[]')
            for c in chunks
        ])
        pg_store.upsert_term_counts(cid, term_counts)

        texts      = [c['raw_text'] for c in chunks]
        embeddings = encode(texts)
        milvus.insert_chunks([
            {'chunk_id': chunks[i]['chunk_id'],
             'course_id': cid,
             'embedding': embeddings[i]}
            for i in range(len(chunks))
        ])

    print(f"\nSeed complete — {len(syllabi)} courses loaded.")
    print("Next step: python scripts/build_graph.py")


if __name__ == '__main__':
    main()
