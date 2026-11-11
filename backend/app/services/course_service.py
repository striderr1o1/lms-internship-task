import psycopg
from fastapi import HTTPException

from app.db import database_error, execute, query_all, query_one, transaction

_COURSE_WITH_COUNT = """
select
  c.id,
  c.name,
  c.status,
  c.created_at,
  p.username as teacher_username,
  count(l.id)::int as lesson_count
from courses as c
join teachers as t on t.id = c.teacher_id
join profiles as p on p.id = t.profile_id
left join lessons as l on l.course_id = c.id
"""

_COURSE_HEADER = """
select
  c.id,
  c.name,
  c.status,
  c.created_at,
  p.username as teacher_username
from courses as c
join teachers as t on t.id = c.teacher_id
join profiles as p on p.id = t.profile_id
"""

_LESSONS = """
select
  l.id,
  l.lesson_number,
  l.title,
  l.body,
  l.mux_asset_id,
  l.youtube_video_id,
  m.status as mux_status,
  m.playback_id as mux_playback_id
from lessons as l
left join mux_assets as m on m.id = l.mux_asset_id
"""


def create_course(teacher_id: str, teacher_username: str, name: str) -> dict:
    try:
        inserted = query_one(
            """
            insert into courses (teacher_id, name)
            values (%s, %s)
            returning id, name, status, created_at
            """,
            (teacher_id, name),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if inserted is None:
        raise HTTPException(status_code=500, detail="Database request failed")
    return _course(inserted, teacher_username=teacher_username, lesson_count=0)


def list_teacher_courses(teacher_id: str) -> list[dict]:
    try:
        found = query_all(
            _COURSE_WITH_COUNT
            + """
            where c.teacher_id = %s
            group by c.id, p.username
            order by c.created_at desc
            """,
            (teacher_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [_listed_course(row) for row in found]


def update_course(teacher_id: str, course_id: str, updates: dict) -> dict:
    columns = [column for column in ("name", "status") if column in updates]
    try:
        with transaction() as conn:
            if columns:
                assignments = ", ".join(f"{column} = %s" for column in columns)
                params = [updates[column] for column in columns]
                params.extend([course_id, teacher_id])
                updated = conn.execute(
                    f"""
                    update courses
                    set {assignments}
                    where id = %s and teacher_id = %s
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
                    where id = %s and teacher_id = %s
                    """,
                    (course_id, teacher_id),
                ).fetchone()
                if owned is None:
                    raise HTTPException(status_code=404, detail="Not found")
            course = conn.execute(
                _COURSE_WITH_COUNT
                + """
                where c.id = %s and c.teacher_id = %s
                group by c.id, p.username
                """,
                (course_id, teacher_id),
            ).fetchone()
            if course is None:
                raise HTTPException(status_code=404, detail="Not found")
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return _listed_course(course)


def delete_course(teacher_id: str, course_id: str) -> None:
    try:
        deleted = execute(
            """
            delete from courses
            where id = %s and teacher_id = %s
            """,
            (course_id, teacher_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Not found")


def list_catalog(student_id: str) -> list[dict]:
    try:
        found = query_all(
            """
            select
              c.id,
              c.name,
              c.status,
              c.created_at,
              p.username as teacher_username,
              count(l.id)::int as lesson_count,
              bool_or(e.id is not null) as enrolled
            from courses as c
            join teachers as t on t.id = c.teacher_id
            join profiles as p on p.id = t.profile_id
            left join lessons as l on l.course_id = c.id
            left join enrollments as e
              on e.course_id = c.id
             and e.student_id = %s
            where c.status = 'active'
            group by c.id, p.username
            order by c.created_at desc
            """,
            (student_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [_listed_course(row, enrolled=bool(row["enrolled"])) for row in found]


def get_student_course(student_id: str, course_id: str) -> dict:
    try:
        with transaction() as conn:
            found = conn.execute(
                _COURSE_HEADER
                + """
                join enrollments as e on e.course_id = c.id
                where e.student_id = %s
                  and e.course_id = %s
                """,
                (student_id, course_id),
            ).fetchone()
            if found is None:
                raise HTTPException(status_code=404, detail="Not found")
            lesson_rows = conn.execute(
                _LESSONS
                + """
                where l.course_id = %s
                order by l.lesson_number
                """,
                (course_id,),
            ).fetchall()
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    lessons = [_student_lesson(row) for row in lesson_rows]
    course = _course(
        found,
        teacher_username=found["teacher_username"] or "",
        lesson_count=len(lessons),
    )
    course["lessons"] = lessons
    return course


def get_teacher_course(teacher_id: str, course_id: str) -> dict:
    try:
        with transaction() as conn:
            found = conn.execute(
                _COURSE_HEADER
                + """
                where c.id = %s and c.teacher_id = %s
                """,
                (course_id, teacher_id),
            ).fetchone()
            if found is None:
                raise HTTPException(status_code=404, detail="Not found")
            lesson_rows = conn.execute(
                _LESSONS
                + """
                where l.course_id = %s
                order by l.lesson_number
                """,
                (course_id,),
            ).fetchall()
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    lessons = [_teacher_lesson(row) for row in lesson_rows]
    course = _course(
        found,
        teacher_username=found["teacher_username"] or "",
        lesson_count=len(lessons),
    )
    course["lessons"] = lessons
    return course


def _load_teacher_lesson(lesson_id: str) -> dict:
    try:
        row = query_one(
            _LESSONS + " where l.id = %s",
            (lesson_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _teacher_lesson(row)


def _listed_course(row: dict, *, enrolled: bool | None = None) -> dict:
    return _course(
        row,
        teacher_username=row["teacher_username"] or "",
        lesson_count=int(row["lesson_count"]),
        enrolled=enrolled,
    )


def _student_lesson(row: dict) -> dict:
    playback_id = None
    if row.get("mux_status") == "ready":
        playback_id = row.get("mux_playback_id")
    return {
        "id": row["id"],
        "lesson_number": row["lesson_number"],
        "title": row["title"],
        "body": row["body"],
        "playback_id": playback_id,
        "youtube_video_id": row.get("youtube_video_id") or None,
    }


def _teacher_lesson(row: dict) -> dict:
    lesson = _student_lesson(row)
    lesson["mux_asset_id"] = row.get("mux_asset_id")
    lesson["video_status"] = row.get("mux_status")
    lesson["video_source"] = _video_source(lesson["mux_asset_id"], lesson["youtube_video_id"])
    return lesson


def _video_source(mux_asset_id: object, youtube_video_id: str | None) -> str | None:
    if mux_asset_id:
        return "mux"
    if youtube_video_id:
        return "youtube"
    return None


def _course(
    row: dict,
    *,
    teacher_username: str,
    lesson_count: int,
    enrolled: bool | None = None,
) -> dict:
    payload = {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "teacher_username": teacher_username,
        "lesson_count": lesson_count,
    }
    if enrolled is not None:
        payload["enrolled"] = enrolled
    return payload
