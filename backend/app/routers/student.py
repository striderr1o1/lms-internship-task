from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import CurrentUser, require_role
from app.schemas.courses import EnrollmentOut, StudentCourseDetail, StudentCourseOut
from app.services import course_service, enrollment_service

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/courses", response_model=list[StudentCourseOut])
def list_courses(user: CurrentUser = Depends(require_role("student"))) -> list[dict]:
    return course_service.list_catalog(user.role_row_id)


@router.get("/courses/{course_id}", response_model=StudentCourseDetail)
def get_course(
    course_id: UUID,
    user: CurrentUser = Depends(require_role("student")),
) -> dict:
    return course_service.get_student_course(user.role_row_id, str(course_id))


@router.post(
    "/courses/{course_id}/enroll",
    response_model=EnrollmentOut,
    status_code=201,
)
def enroll(
    course_id: UUID,
    user: CurrentUser = Depends(require_role("student")),
) -> dict:
    return enrollment_service.enroll(user.role_row_id, str(course_id))


@router.get("/enrollments", response_model=list[StudentCourseOut])
def list_enrollments(user: CurrentUser = Depends(require_role("student"))) -> list[dict]:
    return enrollment_service.list_enrollments(user.role_row_id)
