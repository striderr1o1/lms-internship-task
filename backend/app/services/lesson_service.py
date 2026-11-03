from uuid import UUID

from fastapi import HTTPException
from postgrest.exceptions import APIError

from app.db import admin, database_error, rows
from app.services.course_service import _teacher_lesson
from app.services.youtube import parse_youtube_video_id


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
        response = admin.rpc(
            "create_lesson",
            {
                "p_course_id": course_id,
                "p_teacher_id": teacher_id,
                "p_title": title,
                "p_body": body,
                "p_mux_asset_id": str(mux_asset_id) if mux_asset_id else None,
                "p_youtube_video_id": youtube_video_id,
            },
        ).execute()
    except APIError as exc:
        raise database_error(exc) from exc

    lesson_id = _scalar_id(response.data)
    return _load_teacher_lesson(lesson_id)


def update_lesson(teacher_id: str, lesson_id: str, updates: dict) -> dict:
    _owned_lesson(teacher_id, lesson_id)
    payload: dict = {}
    if "title" in updates:
        payload["title"] = updates["title"]
    if "body" in updates:
        payload["body"] = updates["body"]
    has_mux = "mux_asset_id" in updates
    has_youtube = "youtube_video_id" in updates
    mux_asset_id = updates.get("mux_asset_id") if has_mux else None
    youtube_video_id = _youtube_video_id(updates.get("youtube_video_id")) if has_youtube else None
    if has_mux and mux_asset_id is not None and has_youtube and youtube_video_id is not None:
        raise HTTPException(
            status_code=422,
            detail="A lesson cannot have both a Mux video and a YouTube video",
        )
    if has_mux:
        if mux_asset_id is None:
            payload["mux_asset_id"] = None
        else:
            _owned_asset(teacher_id, str(mux_asset_id))
            payload["mux_asset_id"] = str(mux_asset_id)
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
    try:
        admin.table("lessons").update(payload).eq("id", lesson_id).execute()
    except APIError as exc:
        raise database_error(exc) from exc
    return _load_teacher_lesson(lesson_id)


def delete_lesson(teacher_id: str, lesson_id: str) -> None:
    try:
        admin.rpc(
            "delete_lesson",
            {"p_lesson_id": lesson_id, "p_teacher_id": teacher_id},
        ).execute()
    except APIError as exc:
        raise database_error(exc) from exc


def _owned_lesson(teacher_id: str, lesson_id: str) -> None:
    found = rows(
        admin.table("lessons")
        .select("id, courses!inner(teacher_id)")
        .eq("id", lesson_id)
        .limit(1)
        .execute()
    )
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    course = found[0].get("courses")
    if isinstance(course, list):
        course = course[0] if course else None
    if not isinstance(course, dict) or course.get("teacher_id") != teacher_id:
        raise HTTPException(status_code=404, detail="Not found")


def _owned_asset(teacher_id: str, asset_id: str) -> None:
    found = rows(
        admin.table("mux_assets")
        .select("id, teacher_id")
        .eq("id", asset_id)
        .limit(1)
        .execute()
    )
    if not found or found[0].get("teacher_id") != teacher_id:
        raise HTTPException(status_code=404, detail="Not found")


def _load_teacher_lesson(lesson_id: str) -> dict:
    found = rows(
        admin.table("lessons")
        .select(
            "id, lesson_number, title, body, mux_asset_id, youtube_video_id, "
            "mux_assets(status, playback_id)"
        )
        .eq("id", lesson_id)
        .limit(1)
        .execute()
    )
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    return _teacher_lesson(found[0])


def _youtube_video_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_youtube_video_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid YouTube URL") from exc


def _scalar_id(data) -> str:
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, str) or not data:
        raise HTTPException(status_code=500, detail="Database request failed")
    return data
