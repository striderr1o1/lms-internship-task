import psycopg
from fastapi import HTTPException

from app.db import database_error, execute, query_all, query_one, transaction

COVER_COLUMNS = (
    "cover_image_url",
    "cover_source",
    "cover_alt",
    "cover_color",
    "cover_blur_hash",
    "cover_unsplash_id",
    "cover_credit_name",
    "cover_credit_url",
)

COVER_SELECT = ",\n  ".join(f"c.{column}" for column in COVER_COLUMNS)

_COURSE_WITH_COUNT = f"""
select
  c.id,
  c.name,
  c.status,
  c.created_at,
  {COVER_SELECT},
  p.username as teacher_username,
  count(l.id)::int as lesson_count
from courses as c
join teachers as t on t.id = c.teacher_id
join profiles as p on p.id = t.profile_id
left join lessons as l on l.course_id = c.id
"""

_COURSE_HEADER = f"""
select
  c.id,
  c.name,
  c.status,
  c.created_at,
  {COVER_SELECT},
  p.username as teacher_username
from courses as c
join teachers as t on t.id = c.teacher_id
join profiles as p on p.id = t.profile_id
"""

_LESSON_BLOCKS = """
select
  l.id,
  l.lesson_number,
  l.title,
  b.id as block_id,
  b.position as block_position,
  b.kind as block_kind,
  b.body as block_body,
  b.mux_asset_id as block_mux_asset_id,
  b.youtube_video_id as block_youtube_video_id,
  m.status as mux_status,
  m.playback_id as mux_playback_id
from lessons as l
left join lesson_blocks as b on b.lesson_id = l.id
left join mux_assets as m on m.id = b.mux_asset_id
"""


def create_course(teacher_id: str, teacher_username: str, name: str) -> dict:
    try:
        inserted = query_one(
            f"""
            insert into courses (teacher_id, name)
            values (%s, %s)
            returning id, name, status, created_at, {", ".join(COVER_COLUMNS)}
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


def get_student_course(student_id: str, course_id: str) -> dict:
    try:
        with transaction() as conn:
            found = conn.execute(
                _COURSE_HEADER
                + """
                join enrollments as e on e.course_id = c.id
                where e.student_id = %s
                  and e.course_id = %s
                  and c.status = 'active'
                """,
                (student_id, course_id),
            ).fetchone()
            if found is None:
                raise HTTPException(status_code=404, detail="Not found")
            lesson_rows = conn.execute(
                _LESSON_BLOCKS
                + """
                where l.course_id = %s
                order by l.lesson_number, b.position
                """,
                (course_id,),
            ).fetchall()
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    lessons = _lessons_from_rows(lesson_rows, teacher=False)
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
                _LESSON_BLOCKS
                + """
                where l.course_id = %s
                order by l.lesson_number, b.position
                """,
                (course_id,),
            ).fetchall()
            student_rows = conn.execute(
                """
                select
                  s.id,
                  p.username
                from enrollments as e
                join students as s on s.id = e.student_id
                join profiles as p on p.id = s.profile_id
                where e.course_id = %s
                order by p.username
                """,
                (course_id,),
            ).fetchall()
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    lessons = _lessons_from_rows(lesson_rows, teacher=True)
    course = _course(
        found,
        teacher_username=found["teacher_username"] or "",
        lesson_count=len(lessons),
    )
    course["lessons"] = lessons
    course["students"] = [
        {"id": row["id"], "username": row["username"] or ""}
        for row in student_rows
    ]
    return course


def _load_teacher_lesson(lesson_id: str) -> dict:
    try:
        rows = query_all(
            _LESSON_BLOCKS + " where l.id = %s order by b.position",
            (lesson_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    lessons = _lessons_from_rows(rows, teacher=True)
    if not lessons:
        raise HTTPException(status_code=404, detail="Not found")
    return lessons[0]


def _listed_course(row: dict, *, enrolled: bool | None = None) -> dict:
    return _course(
        row,
        teacher_username=row["teacher_username"] or "",
        lesson_count=int(row["lesson_count"]),
        enrolled=enrolled,
    )


def _lessons_from_rows(rows: list[dict], *, teacher: bool) -> list[dict]:
    lessons: list[dict] = []
    index: dict[object, dict] = {}
    for row in rows:
        lesson = index.get(row["id"])
        if lesson is None:
            lesson = {
                "id": row["id"],
                "lesson_number": row["lesson_number"],
                "title": row["title"],
                "blocks": [],
            }
            index[row["id"]] = lesson
            lessons.append(lesson)
        block = _block(row, teacher=teacher)
        if block is not None:
            lesson["blocks"].append(block)
    return lessons


def _block(row: dict, *, teacher: bool) -> dict | None:
    if row["block_id"] is None:
        return None
    if row["block_kind"] == "text":
        body = row["block_body"]
        return {
            "id": row["block_id"],
            "position": row["block_position"],
            "kind": "text",
            "body": body if isinstance(body, str) else "",
        }
    playback_id = None
    if row.get("mux_status") == "ready":
        playback_id = row.get("mux_playback_id")
    block = {
        "id": row["block_id"],
        "position": row["block_position"],
        "kind": "video",
        "playback_id": playback_id,
        "youtube_video_id": row.get("block_youtube_video_id"),
    }
    if teacher:
        mux_asset_id = row.get("block_mux_asset_id")
        block["mux_asset_id"] = mux_asset_id
        block["video_status"] = row.get("mux_status")
        block["video_source"] = "mux" if mux_asset_id is not None else "youtube"
    return block


def course_cover(row: dict) -> dict | None:
    image_url = row.get("cover_image_url")
    if not isinstance(image_url, str) or not image_url:
        return None
    return {
        "image_url": image_url,
        "source": row.get("cover_source"),
        "alt": row.get("cover_alt"),
        "color": row.get("cover_color"),
        "blur_hash": row.get("cover_blur_hash"),
        "unsplash_id": row.get("cover_unsplash_id"),
        "credit_name": row.get("cover_credit_name"),
        "credit_url": row.get("cover_credit_url"),
    }


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
        "cover": course_cover(row),
    }
    if enrolled is not None:
        payload["enrolled"] = enrolled
    return payload
