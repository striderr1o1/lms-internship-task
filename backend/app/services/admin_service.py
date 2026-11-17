from uuid import UUID

import psycopg
from fastapi import HTTPException

from app.db import database_error, execute, query_all, query_one, transaction
from app.services.course_service import COVER_COLUMNS, COVER_SELECT, _COURSE_WITH_COUNT, _course, course_cover
from app.services.cover_service import prepare_cover, track_unsplash_download


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
            f"""
            select
              t.id as teacher_id,
              p.username as username,
              c.id as course_id,
              c.name as course_name,
              c.status as course_status,
              {COVER_SELECT},
              s.id as student_id,
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
                "students": {},
            }
            for column in COVER_COLUMNS:
                course[column] = row[column]
            courses[course_id] = course
        student_id = row["student_id"]
        if student_id is not None and student_id not in course["students"]:
            course["students"][student_id] = {
                "id": student_id,
                "username": row["student_username"] or "",
            }

    teachers = []
    for teacher_id, username in teacher_names.items():
        courses = list(courses_by_teacher.get(teacher_id, {}).values())
        listed = []
        for course in courses:
            listed.append(
                {
                    "id": course["id"],
                    "name": course["name"],
                    "status": course["status"],
                    "students": sorted(
                        course["students"].values(),
                        key=lambda student: student["username"],
                    ),
                    "cover": course_cover(course),
                }
            )
        listed.sort(key=lambda course: course["name"])
        teachers.append(
            {
                "teacher_id": teacher_id,
                "username": username,
                "courses": listed,
            }
        )
    teachers.sort(key=lambda teacher: teacher["username"])
    return {
        "student_count": int(counts["student_count"]),
        "teacher_count": int(counts["teacher_count"]),
        "course_count": int(counts["course_count"]),
        "teachers": teachers,
    }


def list_teachers() -> list[dict]:
    try:
        found = query_all(
            """
            select
              t.id as teacher_id,
              p.username
            from teachers as t
            join profiles as p on p.id = t.profile_id
            order by p.username
            """
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [
        {"teacher_id": row["teacher_id"], "username": row["username"] or ""}
        for row in found
    ]


def list_students() -> list[dict]:
    try:
        found = query_all(
            """
            select
              s.id,
              p.username,
              p.email
            from students as s
            join profiles as p on p.id = s.profile_id
            order by p.username
            """
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [
        {
            "id": row["id"],
            "username": row["username"] or "",
            "email": row["email"] or "",
        }
        for row in found
    ]


def create_course(
    teacher_id: str,
    name: str,
    student_ids: list[str],
    cover: dict | None = None,
) -> dict:
    cover_values, download_location = prepare_cover(cover)
    distinct_student_ids = list(dict.fromkeys(UUID(student_id) for student_id in student_ids))
    try:
        with transaction() as conn:
            teacher = conn.execute(
                """
                select t.id, p.username
                from teachers as t
                join profiles as p on p.id = t.profile_id
                where t.id = %s
                """,
                (teacher_id,),
            ).fetchone()
            if teacher is None:
                raise HTTPException(status_code=404, detail="Not found")
            if distinct_student_ids:
                found = conn.execute(
                    """
                    select id
                    from students
                    where id = any(%s)
                    """,
                    (distinct_student_ids,),
                ).fetchall()
                if len(found) != len(distinct_student_ids):
                    raise HTTPException(status_code=404, detail="Not found")
            cover_sql = ", ".join(COVER_COLUMNS)
            cover_params = tuple(cover_values[column] for column in COVER_COLUMNS)
            inserted = conn.execute(
                f"""
                insert into courses (
                  teacher_id,
                  name,
                  status,
                  {cover_sql}
                )
                values (%s, %s, 'active', {", ".join(["%s"] * len(COVER_COLUMNS))})
                returning id, name, status, created_at, {cover_sql}
                """,
                (teacher_id, name, *cover_params),
            ).fetchone()
            if inserted is None:
                raise HTTPException(status_code=500, detail="Database request failed")
            if distinct_student_ids:
                conn.execute(
                    """
                    insert into enrollments (student_id, course_id)
                    select s.id, %s
                    from students as s
                    where s.id = any(%s)
                    """,
                    (inserted["id"], distinct_student_ids),
                )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    track_unsplash_download(download_location)
    return _course(
        inserted,
        teacher_username=teacher["username"] or "",
        lesson_count=0,
    )


def update_course(course_id: str, updates: dict) -> dict:
    download_location = None
    cover_values = None
    if "cover" in updates:
        cover_values, download_location = prepare_cover(updates["cover"])
    columns = [column for column in ("name", "status") if column in updates]
    try:
        with transaction() as conn:
            assignments = [f"{column} = %s" for column in columns]
            params: list[object] = [updates[column] for column in columns]
            if cover_values is not None:
                for column in COVER_COLUMNS:
                    assignments.append(f"{column} = %s")
                    params.append(cover_values[column])
            if assignments:
                params.append(course_id)
                updated = conn.execute(
                    f"""
                    update courses
                    set {", ".join(assignments)}
                    where id = %s
                    """,
                    params,
                ).rowcount
                if updated == 0:
                    raise HTTPException(status_code=404, detail="Not found")
            else:
                owned = conn.execute(
                    """
                    select id
                    from courses
                    where id = %s
                    """,
                    (course_id,),
                ).fetchone()
                if owned is None:
                    raise HTTPException(status_code=404, detail="Not found")
            course = conn.execute(
                _COURSE_WITH_COUNT
                + """
                where c.id = %s
                group by c.id, p.username
                """,
                (course_id,),
            ).fetchone()
            if course is None:
                raise HTTPException(status_code=404, detail="Not found")
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    track_unsplash_download(download_location)
    return _course(
        course,
        teacher_username=course["teacher_username"] or "",
        lesson_count=int(course["lesson_count"]),
    )


def delete_course(course_id: str) -> None:
    try:
        deleted = execute(
            """
            delete from courses
            where id = %s
            """,
            (course_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Not found")


def add_student(course_id: str, student_id: str) -> dict:
    try:
        inserted = query_one(
            """
            insert into enrollments (student_id, course_id)
            select s.id, c.id
            from students as s
            cross join courses as c
            where s.id = %s
              and c.id = %s
            returning course_id, student_id, enrolled_at
            """,
            (student_id, course_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc, conflict="Already enrolled") from exc
    if inserted is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "course_id": inserted["course_id"],
        "student_id": inserted["student_id"],
        "enrolled_at": inserted["enrolled_at"].isoformat(),
    }


def remove_student(course_id: str, student_id: str) -> None:
    try:
        deleted = execute(
            """
            delete from enrollments
            where course_id = %s
              and student_id = %s
            """,
            (course_id, student_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Not found")


def _admin_account(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"] or "",
        "email": row["email"] or "",
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
    }
