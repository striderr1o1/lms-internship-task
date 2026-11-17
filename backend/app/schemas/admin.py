from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.courses import CourseCover, CourseStudent


class OverviewCourse(BaseModel):
    id: UUID
    name: str
    status: Literal["active", "inactive"]
    students: list[CourseStudent]
    cover: CourseCover | None


class OverviewTeacher(BaseModel):
    teacher_id: UUID
    username: str
    courses: list[OverviewCourse]


class Overview(BaseModel):
    student_count: int
    teacher_count: int
    course_count: int
    teachers: list[OverviewTeacher]


class AdminAccount(BaseModel):
    id: UUID
    username: str
    email: str
    status: Literal["pending", "approved"]
    created_at: str


class AdminTeacher(BaseModel):
    teacher_id: UUID
    username: str


class AdminStudent(BaseModel):
    id: UUID
    username: str
    email: str


class AdminAddStudent(BaseModel):
    student_id: UUID


class AdminEnrollmentOut(BaseModel):
    course_id: UUID
    student_id: UUID
    enrolled_at: str
