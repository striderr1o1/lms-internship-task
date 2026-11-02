from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.db import admin, database_error, rows
from app.services.course_service import _course, _lesson_counts, _username

_COURSE_COLUMNS = "id, name, status, created_at, teachers(profiles(username))"


def enroll(student_id: str, course_id: str) -> dict:
    found = rows(
        admin.table("courses").select("id, status").eq("id", course_id).limit(1).execute()
    )
    if not found or found[0]["status"] != "active":
        raise HTTPException(status_code=404, detail="Not found")
    try:
        inserted = rows(
            admin.table("enrollments")
            .insert({"student_id": student_id, "course_id": course_id})
            .execute()
        )
    except APIError as exc:
        raise database_error(exc, conflict="Already enrolled") from exc
    if not inserted:
        raise HTTPException(status_code=500, detail="Database request failed")
    return {"course_id": inserted[0]["course_id"], "enrolled_at": inserted[0]["enrolled_at"]}


def list_enrollments(student_id: str) -> list[dict]:
    found = rows(
        admin.table("enrollments")
        .select(f"enrolled_at, course_id, courses({_COURSE_COLUMNS})")
        .eq("student_id", student_id)
        .order("enrolled_at", desc=True)
        .execute()
    )
    courses = []
    for row in found:
        course = row.get("courses")
        if isinstance(course, list):
            course = course[0] if course else None
        if isinstance(course, dict):
            courses.append(course)
    counts = _lesson_counts([course["id"] for course in courses])
    return [
        _course(
            course,
            teacher_username=_username(course),
            lesson_count=counts.get(course["id"], 0),
            enrolled=True,
        )
        for course in courses
    ]
