from fastapi import APIRouter, HTTPException
import storage.postgres_store as pg_store

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
