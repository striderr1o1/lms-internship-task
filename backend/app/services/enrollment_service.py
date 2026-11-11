import psycopg
from fastapi import HTTPException

from app.db import database_error, query_all, query_one
from app.services.course_service import _course


def enroll(student_id: str, course_id: str) -> dict:
    try:
        inserted = query_one(
            """
            insert into enrollments (student_id, course_id)
            select %s, c.id
            from courses as c
            where c.id = %s
              and c.status = 'active'
            returning course_id, enrolled_at
            """,
            (student_id, course_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc, conflict="Already enrolled") from exc
    if inserted is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "course_id": inserted["course_id"],
        "enrolled_at": inserted["enrolled_at"].isoformat(),
    }


def list_enrollments(student_id: str) -> list[dict]:
    try:
        found = query_all(
            """
            select
              c.id,
              c.name,
              c.status,
              c.created_at,
              p.username as teacher_username,
              count(l.id)::int as lesson_count
            from enrollments as e
            join courses as c on c.id = e.course_id
            join teachers as t on t.id = c.teacher_id
            join profiles as p on p.id = t.profile_id
            left join lessons as l on l.course_id = c.id
            where e.student_id = %s
            group by e.enrolled_at, c.id, p.username
            order by e.enrolled_at desc
            """,
            (student_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [
        _course(
            course,
            teacher_username=course["teacher_username"] or "",
            lesson_count=int(course["lesson_count"]),
            enrolled=True,
        )
        for course in found
    ]
