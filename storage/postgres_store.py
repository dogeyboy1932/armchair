import json
from typing import Optional
import psycopg2
import psycopg2.pool
from psycopg2.extras import execute_values
import config

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=10,
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            dbname=config.POSTGRES_DB,
            user=config.POSTGRES_USER,
            password=config.POSTGRES_PASSWORD,
        )
    return _pool


class _Conn:
    """Borrow a connection from the pool, auto-commit or rollback."""
    def __enter__(self):
        self.conn = _get_pool().getconn()
        self.cur  = self.conn.cursor()
        return self.cur

    def __exit__(self, exc_type, *_):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.cur.close()
        _get_pool().putconn(self.conn)


_DDL = """
CREATE TABLE IF NOT EXISTS courses (
    course_id   VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    description TEXT,
    prereqs     TEXT,
    credits     INTEGER DEFAULT 0,
    sequence    INTEGER DEFAULT 0,
    course_type VARCHAR DEFAULT '',
    instructors TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id   VARCHAR PRIMARY KEY,
    course_id  VARCHAR REFERENCES courses(course_id) ON DELETE CASCADE,
    chunk_type VARCHAR,
    raw_text   TEXT NOT NULL,
    keyphrases TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS term_counts (
    course_id VARCHAR NOT NULL,
    term      VARCHAR NOT NULL,
    count     INTEGER NOT NULL,
    PRIMARY KEY (course_id, term)
);

CREATE TABLE IF NOT EXISTS similarity_cache (
    course_a      VARCHAR NOT NULL,
    course_b      VARCHAR NOT NULL,
    final_score   FLOAT,
    lex_score     FLOAT,
    sem_score     FLOAT,
    jsd           FLOAT,
    driving_terms TEXT    DEFAULT '[]',
    computed_at   TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (course_a, course_b)
);
"""


def init_schema():
    with _Conn() as cur:
        cur.execute(_DDL)


def upsert_course(course_id, name, description='', prereqs='',
                  credits=0, sequence=0, course_type='', instructors=''):
    sql = """
    INSERT INTO courses
        (course_id, name, description, prereqs, credits, sequence, course_type, instructors)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (course_id) DO UPDATE SET
        name=EXCLUDED.name, description=EXCLUDED.description,
        prereqs=EXCLUDED.prereqs, credits=EXCLUDED.credits,
        sequence=EXCLUDED.sequence, course_type=EXCLUDED.course_type,
        instructors=EXCLUDED.instructors
    """
    with _Conn() as cur:
        cur.execute(sql, (course_id, name, description, prereqs,
                          credits, sequence, course_type, instructors))


def upsert_chunks(rows: list[tuple]):
    """rows: (chunk_id, course_id, chunk_type, raw_text, keyphrases_json)"""
    sql = """
    INSERT INTO chunks (chunk_id, course_id, chunk_type, raw_text, keyphrases)
    VALUES %s
    ON CONFLICT (chunk_id) DO UPDATE SET
        raw_text=EXCLUDED.raw_text, keyphrases=EXCLUDED.keyphrases
    """
    with _Conn() as cur:
        execute_values(cur, sql, rows)


def upsert_term_counts(course_id: str, counts: dict):
    rows = [(course_id, term, cnt) for term, cnt in counts.items()]
    if not rows:
        return
    sql = """
    INSERT INTO term_counts (course_id, term, count) VALUES %s
    ON CONFLICT (course_id, term) DO UPDATE SET count=EXCLUDED.count
    """
    with _Conn() as cur:
        execute_values(cur, sql, rows)


def get_all_term_counts() -> dict:
    """Returns {course_id: {term: count}}"""
    with _Conn() as cur:
        cur.execute("SELECT course_id, term, count FROM term_counts")
        rows = cur.fetchall()
    result: dict = {}
    for course_id, term, count in rows:
        result.setdefault(course_id, {})[term] = count
    return result


def get_all_courses() -> list[tuple]:
    with _Conn() as cur:
        cur.execute("SELECT course_id, name, description, prereqs, credits, course_type, instructors "
                    "FROM courses ORDER BY sequence, course_id")
        return cur.fetchall()


def get_chunks_for_course(course_id: str) -> list[tuple]:
    with _Conn() as cur:
        cur.execute("SELECT chunk_id, raw_text FROM chunks WHERE course_id=%s", (course_id,))
        return cur.fetchall()


def upsert_similarity(course_a: str, course_b: str, final_score: float,
                      lex_score: float, sem_score: float, jsd: float,
                      driving_terms: list):
    # Always store with lexicographic key order so lookups are consistent
    a, b = sorted([course_a, course_b])
    sql = """
    INSERT INTO similarity_cache
        (course_a, course_b, final_score, lex_score, sem_score, jsd, driving_terms)
    VALUES (%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (course_a, course_b) DO UPDATE SET
        final_score=EXCLUDED.final_score, lex_score=EXCLUDED.lex_score,
        sem_score=EXCLUDED.sem_score, jsd=EXCLUDED.jsd,
        driving_terms=EXCLUDED.driving_terms, computed_at=NOW()
    """
    with _Conn() as cur:
        cur.execute(sql, (a, b, final_score, lex_score, sem_score, jsd,
                          json.dumps(driving_terms)))


def get_similarity(course_a: str, course_b: str) -> Optional[dict]:
    a, b = sorted([course_a, course_b])
    with _Conn() as cur:
        cur.execute(
            "SELECT course_a, course_b, final_score, lex_score, sem_score, jsd, driving_terms "
            "FROM similarity_cache WHERE course_a=%s AND course_b=%s",
            (a, b)
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        'course_a': row[0], 'course_b': row[1],
        'final_score': row[2], 'lex_score': row[3],
        'sem_score': row[4], 'jsd': row[5],
        'driving_terms': json.loads(row[6]) if row[6] else [],
    }


def get_neighbors(course_id: str, top: int = 10) -> list[dict]:
    with _Conn() as cur:
        cur.execute("""
            SELECT
                CASE WHEN course_a=%s THEN course_b ELSE course_a END AS other,
                final_score, lex_score, sem_score, driving_terms
            FROM similarity_cache
            WHERE course_a=%s OR course_b=%s
            ORDER BY final_score DESC
            LIMIT %s
        """, (course_id, course_id, course_id, top))
        rows = cur.fetchall()
    return [
        {
            'course_id':    r[0],
            'final_score':  r[1],
            'lex_score':    r[2],
            'sem_score':    r[3],
            'driving_terms': json.loads(r[4]) if r[4] else [],
        }
        for r in rows
    ]


def drop_all():
    with _Conn() as cur:
        cur.execute(
            "DROP TABLE IF EXISTS similarity_cache, term_counts, chunks, courses CASCADE"
        )
