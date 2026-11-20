from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.deps import CurrentUser, require_role
from app.schemas.courses import (
    CourseOut,
    LessonCreate,
    LessonUpdate,
    TeacherCourseDetail,
    TeacherLesson,
    UploadOut,
    VideoOut,
)
from app.services import course_service, lesson_service, mux_service

router = APIRouter(prefix="/teacher", tags=["teacher"])


def _block_rows(blocks: list) -> list[dict]:
    rows: list[dict] = []
    for block in blocks:
        if block.kind == "text":
            rows.append(
                {
                    "kind": "text",
                    "body": block.body,
                    "mux_asset_id": None,
                    "youtube_video_id": None,
                }
            )
            continue
        rows.append(
            {
                "kind": "video",
                "body": "",
                "mux_asset_id": block.mux_asset_id,
                "youtube_video_id": block.youtube_video_id,
            }
        )
    return rows


@router.get("/courses", response_model=list[CourseOut])
def list_courses(user: CurrentUser = Depends(require_role("teacher"))) -> list[dict]:
    return course_service.list_teacher_courses(user.role_row_id)


@router.get("/courses/{course_id}", response_model=TeacherCourseDetail)
def get_course(
    course_id: UUID,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    return course_service.get_teacher_course(user.role_row_id, str(course_id))


@router.post(
    "/courses/{course_id}/lessons",
    response_model=TeacherLesson,
    status_code=201,
)
def create_lesson(
    course_id: UUID,
    body: LessonCreate,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    return lesson_service.create_lesson(
        user.role_row_id,
        str(course_id),
        body.title,
        _block_rows(body.blocks),
    )


@router.patch("/lessons/{lesson_id}", response_model=TeacherLesson)
def update_lesson(
    lesson_id: UUID,
    body: LessonUpdate,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    updates: dict = {}
    if "title" in body.model_fields_set:
        updates["title"] = body.title
    if "blocks" in body.model_fields_set and body.blocks is not None:
        updates["blocks"] = _block_rows(body.blocks)
    return lesson_service.update_lesson(
        user.role_row_id,
        str(lesson_id),
        updates,
    )


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(
    lesson_id: UUID,
    user: CurrentUser = Depends(require_role("teacher")),
) -> Response:
    lesson_service.delete_lesson(user.role_row_id, str(lesson_id))
    return Response(status_code=204)


@router.post("/videos/uploads", response_model=UploadOut, status_code=201)
def create_upload(user: CurrentUser = Depends(require_role("teacher"))) -> dict:
    return mux_service.create_upload(user.role_row_id)


@router.get("/videos/{video_id}", response_model=VideoOut)
def get_video(
    video_id: UUID,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    return mux_service.get_video(user.role_row_id, str(video_id))
