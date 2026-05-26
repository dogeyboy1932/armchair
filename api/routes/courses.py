from fastapi import APIRouter, HTTPException
import storage.postgres.store as pg_store

router = APIRouter()


@router.get("")
def list_courses():
    rows = pg_store.get_all_courses()
    return [
        {
            "course_id":   r[0],
            "name":        r[1],
            "description": r[2],
            "prereqs":     r[3],
            "credits":     r[4],
            "course_type": r[5],
            "instructors": r[6],
        }
        for r in rows
    ]


@router.get("/{course_id:path}/topics")
def get_course_topics(course_id: str):
    """Return all labeled topics for a course with their category distributions."""
    topics = pg_store.get_topic_texts_for_course(course_id, limit=200)
    if not topics:
        raise HTTPException(404, detail=f"No topics found for '{course_id}'")
    import psycopg2
    import config, json
    conn = psycopg2.connect(
        host=config.POSTGRES_HOST, port=config.POSTGRES_PORT,
        dbname=config.POSTGRES_DB, user=config.POSTGRES_USER, password=config.POSTGRES_PASSWORD
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT topic_text, categories, COALESCE(tags,'[]') FROM topic_categories WHERE course_id=%s ORDER BY topic_text",
        (course_id,)
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [
        {
            "topic_text": r[0],
            "categories": r[1] if isinstance(r[1], dict) else json.loads(r[1]),
            "tags":       r[2] if isinstance(r[2], list) else json.loads(r[2]),
        }
        for r in rows
    ]


@router.get("/{course_id:path}")
def get_course(course_id: str):
    rows = pg_store.get_all_courses()
    for r in rows:
        if r[0].lower() == course_id.lower():
            return {
                "course_id":   r[0],
                "name":        r[1],
                "description": r[2],
                "prereqs":     r[3],
                "credits":     r[4],
                "course_type": r[5],
                "instructors": r[6],
            }
    raise HTTPException(404, detail=f"Course '{course_id}' not found")
