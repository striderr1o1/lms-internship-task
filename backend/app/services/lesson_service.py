from uuid import UUID

import psycopg
from fastapi import HTTPException

from app.db import database_error, query_one, transaction
from app.services.course_service import _load_teacher_lesson
from app.services.youtube import parse_youtube_video_id

_UPDATABLE = ("title", "body", "mux_asset_id", "youtube_video_id")


def create_lesson(
    teacher_id: str,
    course_id: str,
    title: str,
    body: str,
    mux_asset_id: UUID | None,
    youtube_video_id: str | None,
) -> dict:
    youtube_video_id = _youtube_video_id(youtube_video_id)
    if mux_asset_id is not None and youtube_video_id is not None:
        raise HTTPException(
            status_code=422,
            detail="A lesson cannot have both a Mux video and a YouTube video",
        )
    try:
        created = query_one(
            """
            select public.create_lesson(%s, %s, %s, %s, %s, %s) as id
            """,
            (course_id, teacher_id, title, body, mux_asset_id, youtube_video_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if created is None or created["id"] is None:
        raise HTTPException(status_code=500, detail="Database request failed")
    return _load_teacher_lesson(str(created["id"]))


def update_lesson(teacher_id: str, lesson_id: str, updates: dict) -> dict:
    try:
        with transaction() as conn:
            owned = conn.execute(
                """
                select c.teacher_id
                from lessons as l
                join courses as c on c.id = l.course_id
                where l.id = %s
                """,
                (lesson_id,),
            ).fetchone()
            if owned is None or str(owned["teacher_id"]) != str(teacher_id):
                raise HTTPException(status_code=404, detail="Not found")

            payload: dict = {}
            if "title" in updates:
                payload["title"] = updates["title"]
            if "body" in updates:
                payload["body"] = updates["body"]
            has_mux = "mux_asset_id" in updates
            has_youtube = "youtube_video_id" in updates
            mux_asset_id = updates.get("mux_asset_id") if has_mux else None
            youtube_video_id = (
                _youtube_video_id(updates.get("youtube_video_id")) if has_youtube else None
            )
            both_videos = (
                has_mux
                and mux_asset_id is not None
                and has_youtube
                and youtube_video_id is not None
            )
            if both_videos:
                raise HTTPException(
                    status_code=422,
                    detail="A lesson cannot have both a Mux video and a YouTube video",
                )
            if has_mux:
                if mux_asset_id is None:
                    payload["mux_asset_id"] = None
                else:
                    _owned_asset(conn, teacher_id, str(mux_asset_id))
                    payload["mux_asset_id"] = mux_asset_id
                    payload["youtube_video_id"] = None
            if has_youtube:
                if youtube_video_id is None:
                    payload["youtube_video_id"] = None
                else:
                    payload["youtube_video_id"] = youtube_video_id
                    payload["mux_asset_id"] = None
            if not payload:
                raise HTTPException(
                    status_code=422,
                    detail="At least one of title, body, mux_asset_id, or youtube_url is required",
                )

            columns = [column for column in _UPDATABLE if column in payload]
            assignments = ", ".join(f"{column} = %s" for column in columns)
            params = [payload[column] for column in columns]
            params.append(lesson_id)
            conn.execute(
                f"update lessons set {assignments} where id = %s",
                params,
            )
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


def _youtube_video_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_youtube_video_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid YouTube URL") from exc
