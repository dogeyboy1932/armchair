import json
import tempfile
from pathlib import Path

import pdfplumber
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

import config
from pipeline.chunker  import chunk_course
from pipeline.encoder  import encode
from scoring.driving_terms    import compute_idf
from scoring.hybrid_scorer    import score_pair
from scoring.language_model   import build_all_lms
from storage import milvus_store as milvus
from storage import neo4j_store  as neo4j
from storage import postgres_store as pg_store

router = APIRouter()


def _pdf_to_text(raw: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(raw)
        tmp = Path(f.name)
    try:
        parts = []
        with pdfplumber.open(tmp) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        return '\n'.join(parts)
    finally:
        tmp.unlink(missing_ok=True)


def _run_ingest(course_id: str, course_name: str, topics: list[str], description: str):
    with open(config.DEFINITIONS_PATH) as f:
        topic_defs = json.load(f)

    course = {
        'id': course_id, 'name': course_name,
        'description': description, 'objectives': [],
        'topics': topics, 'definitions': [],
    }
    chunks, term_counts = chunk_course(course, topic_defs)

    # Persist metadata
    pg_store.upsert_course(course_id, course_name, description)
    neo4j.upsert_course(course_id, course_name, description)

    # Persist chunks + term counts
    pg_store.upsert_chunks([
        (c['chunk_id'], c['course_id'], c['chunk_type'], c['raw_text'], '[]')
        for c in chunks
    ])
    pg_store.upsert_term_counts(course_id, term_counts)

    # Only embed topic + definition chunks (description/objective are too generic)
    embed_chunks = [c for c in chunks if c['chunk_type'] in ('topic', 'definition')]
    if embed_chunks:
        embeddings = encode([c['raw_text'] for c in embed_chunks])
        milvus.insert_chunks([
            {'chunk_id': embed_chunks[i]['chunk_id'], 'course_id': course_id,
             'embedding': embeddings[i]}
            for i in range(len(embed_chunks))
        ])

    # Recompute scores for this course vs all others
    all_counts = pg_store.get_all_term_counts()
    lms = build_all_lms(all_counts)
    idf = compute_idf(all_counts)
    for other_id in lms:
        if other_id != course_id:
            score_pair(course_id, other_id, lms, idf, all_counts)

    # Re-run community detection so graph clusters update
    try:
        neo4j.run_community_detection()
    except Exception as e:
        print(f"[ingest] community detection skipped: {e}")

    print(f"[ingest] '{course_name}' done — {len(chunks)} chunks, "
          f"{len(lms)-1} pairs scored.")


@router.post("/pdf")
async def ingest_pdf(
    background_tasks: BackgroundTasks,
    file:        UploadFile = File(...),
    course_id:   str        = Form(...),
    course_name: str        = Form(...),
):
    """
    Upload a PDF syllabus. Runs the full ingestion pipeline in the background:
    parse → chunk → embed → store → score all pairs involving the new course.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, detail="Only PDF files are supported")

    raw  = await file.read()
    text = _pdf_to_text(raw)
    if not text.strip():
        raise HTTPException(400, detail="Could not extract text from the PDF")

    # Treat non-blank lines as topic candidates
    topics = [
        line.strip() for line in text.splitlines()
        if len(line.strip()) > 5
    ][:120]

    background_tasks.add_task(
        _run_ingest, course_id, course_name, topics, text[:2000]
    )
    return {
        "message":   f"Ingestion started for '{course_name}'.",
        "course_id": course_id,
        "note":      f"Check GET /courses/{course_id} in ~30 s.",
    }
