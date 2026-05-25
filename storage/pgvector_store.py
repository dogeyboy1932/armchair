"""
pgvector-backed vector store. Drop-in replacement for storage/milvus_store.py.

Uses the SAME Postgres connection as storage/postgres_store.py and requires
the `vector` extension (Supabase has it preinstalled; CREATE EXTENSION is a no-op
if already present).

Public API matches milvus_store.py exactly so both can be swapped via
storage/vector_store.py based on the VECTOR_BACKEND env var.
"""
from __future__ import annotations

import numpy as np
from psycopg2.extras import execute_values

from storage.postgres_store import _Conn

DIM = 768

_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id  VARCHAR PRIMARY KEY,
    course_id VARCHAR NOT NULL,
    embedding vector({DIM}) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunk_embeddings_course_id_idx
    ON chunk_embeddings (course_id);
"""


def _vec_literal(arr: np.ndarray | list) -> str:
    """Format a numpy array as a pgvector literal: '[0.1, 0.2, ...]'."""
    if isinstance(arr, np.ndarray):
        arr = arr.tolist()
    return "[" + ",".join(f"{float(x):.7g}" for x in arr) + "]"


# ── Schema bootstrap ──────────────────────────────────────────────────────────
def get_or_create_collection():
    """Equivalent of Milvus' get_or_create_collection — ensures table+index exist."""
    with _Conn() as cur:
        cur.execute(_DDL)


# ── Inserts ──────────────────────────────────────────────────────────────────
def insert_chunks(chunks: list[dict]):
    """chunks: list of {chunk_id, course_id, embedding (np.ndarray shape (768,))}"""
    if not chunks:
        return
    rows = [
        (c["chunk_id"], c["course_id"], _vec_literal(c["embedding"]))
        for c in chunks
    ]
    sql = """
    INSERT INTO chunk_embeddings (chunk_id, course_id, embedding)
    VALUES %s
    ON CONFLICT (chunk_id) DO UPDATE SET
        course_id = EXCLUDED.course_id,
        embedding = EXCLUDED.embedding
    """
    with _Conn() as cur:
        execute_values(cur, sql, rows, template="(%s, %s, %s::vector)")


# ── Queries ──────────────────────────────────────────────────────────────────
def get_embeddings_for_course(course_id: str) -> list[np.ndarray]:
    """All embeddings for one course, in arbitrary order."""
    with _Conn() as cur:
        cur.execute(
            "SELECT embedding FROM chunk_embeddings WHERE course_id = %s",
            (course_id,),
        )
        rows = cur.fetchall()
    return [_parse_vector(r[0]) for r in rows]


def get_chunk_embedding(chunk_id: str) -> np.ndarray | None:
    with _Conn() as cur:
        cur.execute(
            "SELECT embedding FROM chunk_embeddings WHERE chunk_id = %s",
            (chunk_id,),
        )
        row = cur.fetchone()
    return _parse_vector(row[0]) if row else None


def get_chunks_with_embeddings(course_id: str) -> dict:
    """{chunk_id: embedding} for all chunks in a course."""
    with _Conn() as cur:
        cur.execute(
            "SELECT chunk_id, embedding FROM chunk_embeddings WHERE course_id = %s",
            (course_id,),
        )
        rows = cur.fetchall()
    return {r[0]: _parse_vector(r[1]) for r in rows}


def search_in_course(
    query_vectors: list[np.ndarray],
    course_id: str,
    limit: int = 1,
) -> list[float]:
    """
    For each query vector return the best cosine similarity score against the
    chunks belonging to course_id. Returns a list of floats (one per query).

    pgvector's `<=>` is COSINE DISTANCE in [0, 2]. Similarity = 1 - distance.
    Since embeddings are L2-normalised at encode time, this is exact cosine.
    """
    if not query_vectors:
        return []
    scores: list[float] = []
    with _Conn() as cur:
        for v in query_vectors:
            cur.execute(
                """
                SELECT 1 - (embedding <=> %s::vector) AS sim
                FROM chunk_embeddings
                WHERE course_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (_vec_literal(v), course_id, _vec_literal(v), limit),
            )
            rows = cur.fetchall()
            scores.append(float(rows[0][0]) if rows else 0.0)
    return scores


def search_global_excluding(
    query_vector: np.ndarray,
    exclude_course_id: str,
    limit: int = 10,
) -> list[dict]:
    """ANN across ALL courses except exclude_course_id, sorted by score desc."""
    lit = _vec_literal(query_vector)
    with _Conn() as cur:
        cur.execute(
            """
            SELECT chunk_id, course_id, 1 - (embedding <=> %s::vector) AS sim
            FROM chunk_embeddings
            WHERE course_id != %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (lit, exclude_course_id, lit, limit),
        )
        rows = cur.fetchall()
    return [
        {"chunk_id": r[0], "course_id": r[1], "score": float(r[2])}
        for r in rows
    ]


# ── Deletes ──────────────────────────────────────────────────────────────────
def delete_course(course_id: str):
    with _Conn() as cur:
        cur.execute("DELETE FROM chunk_embeddings WHERE course_id = %s", (course_id,))


def drop_collection():
    with _Conn() as cur:
        cur.execute("DROP TABLE IF EXISTS chunk_embeddings")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _parse_vector(val) -> np.ndarray:
    """pgvector returns '[0.1,0.2,...]' as text — parse to np.ndarray."""
    if isinstance(val, (list, tuple)):
        return np.array(val, dtype=np.float32)
    s = str(val).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return np.array([float(x) for x in s.split(",") if x.strip()], dtype=np.float32)
