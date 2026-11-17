import time
from threading import Lock

import psycopg
from fastapi import HTTPException

from app.db import database_error, query_all, query_one
from app.services.course_service import COVER_SELECT, course_cover

_TTL_SECONDS = 60
_lock = Lock()
_stats_cache: tuple[float, dict] | None = None
_featured_cache: tuple[float, list[dict]] | None = None


def stats() -> dict:
    global _stats_cache
    now = time.monotonic()
    with _lock:
        if _stats_cache is not None and _stats_cache[0] > now:
            return _stats_cache[1]
    payload = _load_stats()
    with _lock:
        _stats_cache = (time.monotonic() + _TTL_SECONDS, payload)
    return payload


def featured_courses() -> list[dict]:
    global _featured_cache
    now = time.monotonic()
    with _lock:
        if _featured_cache is not None and _featured_cache[0] > now:
            return _featured_cache[1]
    payload = _load_featured()
    with _lock:
        _featured_cache = (time.monotonic() + _TTL_SECONDS, payload)
    return payload


def _load_stats() -> dict:
    try:
        row = query_one(
            """
            select
              (select count(*)::int from courses where status = 'active') as courses,
              (
                select count(*)::int
                from lessons as l
                join courses as c on c.id = l.course_id
                where c.status = 'active'
              ) as lessons,
              (
                select count(distinct e.student_id)::int
                from enrollments as e
                join courses as c on c.id = e.course_id
                where c.status = 'active'
              ) as learners
            """
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=500, detail="Database request failed")
    return {
        "courses": int(row["courses"]),
        "lessons": int(row["lessons"]),
        "learners": int(row["learners"]),
    }


def _load_featured() -> list[dict]:
    try:
        rows = query_all(
            f"""
            select
              c.id,
              c.name,
              {COVER_SELECT},
              p.username as teacher_username,
              count(l.id)::int as lesson_count
            from courses as c
            join teachers as t on t.id = c.teacher_id
            join profiles as p on p.id = t.profile_id
            left join lessons as l on l.course_id = c.id
            where c.status = 'active'
            group by c.id, p.username
            order by c.created_at desc
            limit 6
            """
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "cover": course_cover(row),
            "lesson_count": int(row["lesson_count"]),
            "teacher_display_name": row["teacher_username"] or "",
        }
        for row in rows
    ]
