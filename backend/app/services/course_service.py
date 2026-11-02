from fastapi import HTTPException

from app.db import admin, rows


def create_course(teacher_id: str, teacher_username: str, name: str) -> dict:
    inserted = rows(
        admin.table("courses").insert({"teacher_id": teacher_id, "name": name}).execute()
    )
    if not inserted:
        raise HTTPException(status_code=500, detail="Database request failed")
    return _course(inserted[0], teacher_username=teacher_username, lesson_count=0)


def list_teacher_courses(teacher_id: str) -> list[dict]:
    found = rows(
        admin.table("courses")
        .select(_COURSE_COLUMNS)
        .eq("teacher_id", teacher_id)
        .order("created_at", desc=True)
        .execute()
    )
    return _with_counts(found)


def update_course(teacher_id: str, course_id: str, updates: dict) -> dict:
    if not _teacher_owns(teacher_id, course_id):
        raise HTTPException(status_code=404, detail="Not found")
    payload = {key: updates[key] for key in ("name", "status") if key in updates}
    if payload:
        admin.table("courses").update(payload).eq("id", course_id).eq(
            "teacher_id", teacher_id
        ).execute()
    course = _teacher_course_row(teacher_id, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Not found")
    counts = _lesson_counts([course_id])
    return _course(
        course,
        teacher_username=_username(course),
        lesson_count=counts.get(course_id, 0),
    )


def delete_course(teacher_id: str, course_id: str) -> None:
    if not _teacher_owns(teacher_id, course_id):
        raise HTTPException(status_code=404, detail="Not found")
    admin.table("courses").delete().eq("id", course_id).eq("teacher_id", teacher_id).execute()


def list_catalog(student_id: str) -> list[dict]:
    found = rows(
        admin.table("courses")
        .select(_COURSE_COLUMNS)
        .eq("status", "active")
        .order("created_at", desc=True)
        .execute()
    )
    enrolled = _enrolled_ids(student_id)
    counts = _lesson_counts([row["id"] for row in found])
    return [
        _course(
            row,
            teacher_username=_username(row),
            lesson_count=counts.get(row["id"], 0),
            enrolled=row["id"] in enrolled,
        )
        for row in found
    ]


def get_student_course(student_id: str, course_id: str) -> dict:
    enrollment = rows(
        admin.table("enrollments")
        .select("id")
        .eq("student_id", student_id)
        .eq("course_id", course_id)
        .limit(1)
        .execute()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Not found")
    found = rows(
        admin.table("courses").select(_COURSE_COLUMNS).eq("id", course_id).limit(1).execute()
    )
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    lessons = _student_lessons(course_id)
    course = _course(
        found[0],
        teacher_username=_username(found[0]),
        lesson_count=len(lessons),
    )
    course["lessons"] = lessons
    return course


def get_teacher_course(teacher_id: str, course_id: str) -> dict:
    course = _teacher_course_row(teacher_id, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Not found")
    lessons = _teacher_lessons(course_id)
    payload = _course(
        course,
        teacher_username=_username(course),
        lesson_count=len(lessons),
    )
    payload["lessons"] = lessons
    return payload


def _teacher_owns(teacher_id: str, course_id: str) -> bool:
    found = rows(
        admin.table("courses")
        .select("id")
        .eq("id", course_id)
        .eq("teacher_id", teacher_id)
        .limit(1)
        .execute()
    )
    return bool(found)


def _teacher_course_row(teacher_id: str, course_id: str) -> dict | None:
    found = rows(
        admin.table("courses")
        .select(_COURSE_COLUMNS)
        .eq("id", course_id)
        .eq("teacher_id", teacher_id)
        .limit(1)
        .execute()
    )
    return found[0] if found else None


def _with_counts(found: list[dict]) -> list[dict]:
    counts = _lesson_counts([row["id"] for row in found])
    return [
        _course(
            row,
            teacher_username=_username(row),
            lesson_count=counts.get(row["id"], 0),
        )
        for row in found
    ]


def _enrolled_ids(student_id: str) -> set[str]:
    found = rows(
        admin.table("enrollments").select("course_id").eq("student_id", student_id).execute()
    )
    return {row["course_id"] for row in found}


def _lesson_counts(course_ids: list[str]) -> dict[str, int]:
    if not course_ids:
        return {}
    found = rows(
        admin.table("lessons").select("course_id").in_("course_id", course_ids).execute()
    )
    counts: dict[str, int] = {}
    for row in found:
        course_id = row["course_id"]
        counts[course_id] = counts.get(course_id, 0) + 1
    return counts


def _student_lessons(course_id: str) -> list[dict]:
    found = rows(
        admin.table("lessons")
        .select("id, lesson_number, title, body, mux_assets(status, playback_id)")
        .eq("course_id", course_id)
        .order("lesson_number")
        .execute()
    )
    return [_student_lesson(row) for row in found]


def _teacher_lessons(course_id: str) -> list[dict]:
    found = rows(
        admin.table("lessons")
        .select(
            "id, lesson_number, title, body, mux_asset_id, mux_assets(status, playback_id)"
        )
        .eq("course_id", course_id)
        .order("lesson_number")
        .execute()
    )
    return [_teacher_lesson(row) for row in found]


def _student_lesson(row: dict) -> dict:
    asset = _asset(row)
    playback_id = None
    if asset is not None and asset.get("status") == "ready":
        playback_id = asset.get("playback_id")
    return {
        "id": row["id"],
        "lesson_number": row["lesson_number"],
        "title": row["title"],
        "body": row["body"],
        "playback_id": playback_id,
    }


def _teacher_lesson(row: dict) -> dict:
    lesson = _student_lesson(row)
    asset = _asset(row)
    lesson["mux_asset_id"] = row.get("mux_asset_id")
    lesson["video_status"] = asset.get("status") if asset is not None else None
    return lesson


def _asset(row: dict) -> dict | None:
    asset = row.get("mux_assets")
    if isinstance(asset, list):
        asset = asset[0] if asset else None
    if not isinstance(asset, dict) or not asset:
        return None
    return asset


def _username(row: dict) -> str:
    teacher = row.get("teachers")
    if isinstance(teacher, list):
        teacher = teacher[0] if teacher else None
    if not isinstance(teacher, dict):
        return ""
    profile = teacher.get("profiles")
    if isinstance(profile, list):
        profile = profile[0] if profile else None
    if not isinstance(profile, dict):
        return ""
    return profile.get("username") or ""


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
        "created_at": row["created_at"],
        "teacher_username": teacher_username,
        "lesson_count": lesson_count,
    }
    if enrolled is not None:
        payload["enrolled"] = enrolled
    return payload


_COURSE_COLUMNS = "id, name, status, created_at, teachers(profiles(username))"
