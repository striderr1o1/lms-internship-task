import psycopg
from fastapi import HTTPException

from app.db import database_error, query_one, transaction
from app.services.course_service import _load_teacher_lesson


def create_lesson(
    teacher_id: str,
    course_id: str,
    title: str,
    blocks: list[dict],
) -> dict:
    try:
        with transaction() as conn:
            _require_owned_assets(conn, teacher_id, blocks)
            created = conn.execute(
                """
                select public.create_lesson(%s, %s, %s) as id
                """,
                (course_id, teacher_id, title),
            ).fetchone()
            if created is None or created["id"] is None:
                raise HTTPException(status_code=500, detail="Database request failed")
            lesson_id = str(created["id"])
            _insert_blocks(conn, lesson_id, blocks)
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return _load_teacher_lesson(lesson_id)


def update_lesson(teacher_id: str, lesson_id: str, updates: dict) -> dict:
    has_title = "title" in updates
    has_blocks = "blocks" in updates
    if not has_title and not has_blocks:
        raise HTTPException(
            status_code=422,
            detail="At least one of title or blocks is required",
        )
    try:
        with transaction() as conn:
            owned = conn.execute(
                """
                select c.teacher_id
                from lessons as l
                join courses as c on c.id = l.course_id
                where l.id = %s
                for update of l
                """,
                (lesson_id,),
            ).fetchone()
            if owned is None or str(owned["teacher_id"]) != str(teacher_id):
                raise HTTPException(status_code=404, detail="Not found")
            if has_blocks:
                _require_owned_assets(conn, teacher_id, updates["blocks"])
            if has_title:
                conn.execute(
                    "update lessons set title = %s where id = %s",
                    (updates["title"], lesson_id),
                )
            if has_blocks:
                conn.execute(
                    "delete from lesson_blocks where lesson_id = %s",
                    (lesson_id,),
                )
                _insert_blocks(conn, lesson_id, updates["blocks"])
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return _load_teacher_lesson(lesson_id)


def delete_lesson(teacher_id: str, lesson_id: str) -> None:
    try:
        query_one(
            "select public.delete_lesson(%s, %s)",
            (lesson_id, teacher_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc


def _require_owned_assets(conn, teacher_id: str, blocks: list[dict]) -> None:
    seen: set[str] = set()
    for block in blocks:
        asset_id = block.get("mux_asset_id")
        if asset_id is None:
            continue
        key = str(asset_id)
        if key in seen:
            continue
        seen.add(key)
        _owned_asset(conn, teacher_id, key)


def _insert_blocks(conn, lesson_id: str, blocks: list[dict]) -> None:
    if not blocks:
        return
    placeholders = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(blocks))
    params: list[object] = []
    for position, block in enumerate(blocks, start=1):
        params.extend(
            (
                lesson_id,
                position,
                block["kind"],
                block["body"],
                block["mux_asset_id"],
                block["youtube_video_id"],
            )
        )
    conn.execute(
        f"""
        insert into lesson_blocks (
          lesson_id, position, kind, body, mux_asset_id, youtube_video_id
        )
        values {placeholders}
        """,
        params,
    )


def _owned_asset(conn, teacher_id: str, asset_id: str) -> None:
    found = conn.execute(
        """
        select teacher_id
        from mux_assets
        where id = %s
        """,
        (asset_id,),
    ).fetchone()
    if found is None or str(found["teacher_id"]) != str(teacher_id):
        raise HTTPException(status_code=404, detail="Not found")
