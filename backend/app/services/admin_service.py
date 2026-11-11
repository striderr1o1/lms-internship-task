import psycopg
from fastapi import HTTPException

from app.db import database_error, query_all, query_one


def overview() -> dict:
    try:
        counts = query_one(
            """
            select
              (select count(*)::int from students) as student_count,
              (select count(*)::int from teachers) as teacher_count,
              (select count(*)::int from courses) as course_count
            """
        )
        rows = query_all(
            """
            select
              t.id as teacher_id,
              p.username as username,
              c.id as course_id,
              c.name as course_name,
              c.status as course_status,
              sp.username as student_username
            from teachers as t
            join profiles as p on p.id = t.profile_id
            left join courses as c on c.teacher_id = t.id
            left join enrollments as e on e.course_id = c.id
            left join students as s on s.id = e.student_id
            left join profiles as sp on sp.id = s.profile_id
            """
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if counts is None:
        raise HTTPException(status_code=500, detail="Database request failed")
    return _overview(counts, rows)


def list_admins(status: str) -> list[dict]:
    try:
        found = query_all(
            """
            select
              a.id,
              p.username,
              p.email,
              a.status,
              a.created_at
            from admins as a
            join profiles as p on p.id = a.profile_id
            where a.status = %s
            order by a.created_at asc
            """,
            (status,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [_admin_account(row) for row in found]


def approve(admin_id: str) -> dict:
    try:
        row = query_one(
            """
            update admins as a
            set status = 'approved'
            from profiles as p
            where a.profile_id = p.id
              and a.id = %s
            returning a.id, p.username, p.email, a.status, a.created_at
            """,
            (admin_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _admin_account(row)


def _overview(counts: dict, rows: list[dict]) -> dict:
    teacher_names: dict = {}
    courses_by_teacher: dict = {}
    for row in rows:
        teacher_id = row["teacher_id"]
        teacher_names[teacher_id] = row["username"] or ""
        courses = courses_by_teacher.setdefault(teacher_id, {})
        course_id = row["course_id"]
        if course_id is None:
            continue
        course = courses.get(course_id)
        if course is None:
            course = {
                "id": course_id,
                "name": row["course_name"],
                "status": row["course_status"],
                "students": [],
            }
            courses[course_id] = course
        if row["student_username"]:
            course["students"].append(row["student_username"])

    teachers = []
    for teacher_id, username in teacher_names.items():
        courses = list(courses_by_teacher.get(teacher_id, {}).values())
        for course in courses:
            course["students"] = sorted(course["students"])
        courses.sort(key=lambda course: course["name"])
        teachers.append(
            {
                "teacher_id": teacher_id,
                "username": username,
                "courses": courses,
            }
        )
    teachers.sort(key=lambda teacher: teacher["username"])
    return {
        "student_count": int(counts["student_count"]),
        "teacher_count": int(counts["teacher_count"]),
        "course_count": int(counts["course_count"]),
        "teachers": teachers,
    }


def _admin_account(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"] or "",
        "email": row["email"] or "",
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
    }
