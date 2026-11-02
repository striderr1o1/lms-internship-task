from fastapi import HTTPException
from postgrest.types import CountMethod
from supabase_auth.errors import AuthError

from app.db import admin, rows


def overview() -> dict:
    teacher_rows = rows(admin.table("teachers").select("id, profiles(username)").execute())
    course_rows = rows(
        admin.table("courses").select("id, teacher_id, name, status").execute()
    )
    enrollment_rows = rows(
        admin.table("enrollments")
        .select("course_id, students(profiles(username))")
        .execute()
    )

    students_by_course: dict[str, list[str]] = {}
    for row in enrollment_rows:
        username = _nested_username(row.get("students"))
        if username:
            students_by_course.setdefault(row["course_id"], []).append(username)

    courses_by_teacher: dict[str, list[dict]] = {}
    for course in course_rows:
        courses_by_teacher.setdefault(course["teacher_id"], []).append(
            {
                "id": course["id"],
                "name": course["name"],
                "status": course["status"],
                "students": sorted(students_by_course.get(course["id"], [])),
            }
        )

    teachers = []
    for teacher in teacher_rows:
        username = _nested_username(teacher.get("profiles"))
        courses = sorted(
            courses_by_teacher.get(teacher["id"], []),
            key=lambda course: course["name"],
        )
        teachers.append(
            {
                "teacher_id": teacher["id"],
                "username": username,
                "courses": courses,
            }
        )
    teachers.sort(key=lambda teacher: teacher["username"])
    return {
        "student_count": _count("students"),
        "teacher_count": _count("teachers"),
        "course_count": _count("courses"),
        "teachers": teachers,
    }


def list_admins(status: str) -> list[dict]:
    found = rows(
        admin.table("admins")
        .select("id, profile_id, status, created_at, profiles(username)")
        .eq("status", status)
        .order("created_at")
        .execute()
    )
    return [_admin_account(row) for row in found]


def approve(admin_id: str) -> dict:
    found = rows(
        admin.table("admins")
        .select("id, profile_id, status, created_at, profiles(username)")
        .eq("id", admin_id)
        .limit(1)
        .execute()
    )
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    admin.table("admins").update({"status": "approved"}).eq("id", admin_id).execute()
    found[0]["status"] = "approved"
    return _admin_account(found[0])


def _admin_account(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": _nested_username(row.get("profiles")),
        "email": _email(row["profile_id"]),
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _email(profile_id: str) -> str:
    try:
        response = admin.auth.admin.get_user_by_id(profile_id)
    except AuthError:
        return ""
    user = response.user
    if user is None or not user.email:
        return ""
    return user.email


def _nested_username(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return ""
    if "username" in value:
        return value.get("username") or ""
    return _nested_username(value.get("profiles"))


def _count(table: str) -> int:
    response = admin.table(table).select("id", count=CountMethod.exact, head=True).execute()
    return response.count or 0
