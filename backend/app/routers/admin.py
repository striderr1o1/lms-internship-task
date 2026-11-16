from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.deps import CurrentUser, require_role
from app.schemas.admin import (
    AdminAccount,
    AdminAddStudent,
    AdminEnrollmentOut,
    AdminStudent,
    AdminTeacher,
    Overview,
)
from app.schemas.courses import AdminCourseCreate, CourseOut, CourseUpdate
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=Overview)
def overview(user: CurrentUser = Depends(require_role("admin"))) -> dict:
    del user
    return admin_service.overview()


@router.get("/admins", response_model=list[AdminAccount])
def list_admins(
    status: Literal["pending", "approved"] = Query(default="pending"),
    user: CurrentUser = Depends(require_role("admin")),
) -> list[dict]:
    del user
    return admin_service.list_admins(status)


@router.post("/admins/{admin_id}/approve", response_model=AdminAccount)
def approve(
    admin_id: UUID,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    del user
    return admin_service.approve(str(admin_id))


@router.get("/teachers", response_model=list[AdminTeacher])
def list_teachers(user: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    del user
    return admin_service.list_teachers()


@router.get("/students", response_model=list[AdminStudent])
def list_students(user: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    del user
    return admin_service.list_students()


@router.post("/courses", response_model=CourseOut, status_code=201)
def create_course(
    body: AdminCourseCreate,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    del user
    return admin_service.create_course(
        str(body.teacher_id),
        body.name,
        [str(student_id) for student_id in body.student_ids],
    )


@router.patch("/courses/{course_id}", response_model=CourseOut)
def update_course(
    course_id: UUID,
    body: CourseUpdate,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    del user
    return admin_service.update_course(str(course_id), body.model_dump(exclude_unset=True))


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(
    course_id: UUID,
    user: CurrentUser = Depends(require_role("admin")),
) -> Response:
    del user
    admin_service.delete_course(str(course_id))
    return Response(status_code=204)


@router.post(
    "/courses/{course_id}/students",
    response_model=AdminEnrollmentOut,
    status_code=201,
)
def add_student(
    course_id: UUID,
    body: AdminAddStudent,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    del user
    return admin_service.add_student(str(course_id), str(body.student_id))


@router.delete("/courses/{course_id}/students/{student_id}", status_code=204)
def remove_student(
    course_id: UUID,
    student_id: UUID,
    user: CurrentUser = Depends(require_role("admin")),
) -> Response:
    del user
    admin_service.remove_student(str(course_id), str(student_id))
    return Response(status_code=204)
