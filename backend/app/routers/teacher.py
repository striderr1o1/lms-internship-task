from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.deps import CurrentUser, require_role
from app.schemas.courses import (
    CourseCreate,
    CourseOut,
    CourseUpdate,
    LessonCreate,
    LessonUpdate,
    TeacherCourseDetail,
    TeacherLesson,
    UploadOut,
    VideoOut,
)
from app.services import course_service, lesson_service, mux_service

router = APIRouter(prefix="/teacher", tags=["teacher"])


@router.get("/courses", response_model=list[CourseOut])
def list_courses(user: CurrentUser = Depends(require_role("teacher"))) -> list[dict]:
    return course_service.list_teacher_courses(user.role_row_id)


@router.post("/courses", response_model=CourseOut, status_code=201)
def create_course(
    body: CourseCreate,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    return course_service.create_course(user.role_row_id, user.username, body.name)


@router.get("/courses/{course_id}", response_model=TeacherCourseDetail)
def get_course(
    course_id: UUID,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    return course_service.get_teacher_course(user.role_row_id, str(course_id))


@router.patch("/courses/{course_id}", response_model=CourseOut)
def update_course(
    course_id: UUID,
    body: CourseUpdate,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    return course_service.update_course(
        user.role_row_id,
        str(course_id),
        body.model_dump(exclude_unset=True),
    )


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(
    course_id: UUID,
    user: CurrentUser = Depends(require_role("teacher")),
) -> Response:
    course_service.delete_course(user.role_row_id, str(course_id))
    return Response(status_code=204)


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
        body.body,
        body.mux_asset_id,
        body.youtube_video_id,
    )


@router.patch("/lessons/{lesson_id}", response_model=TeacherLesson)
def update_lesson(
    lesson_id: UUID,
    body: LessonUpdate,
    user: CurrentUser = Depends(require_role("teacher")),
) -> dict:
    updates = body.model_dump(exclude_unset=True)
    if "youtube_url" in updates:
        updates["youtube_video_id"] = body.youtube_video_id
        del updates["youtube_url"]
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
