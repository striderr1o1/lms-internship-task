from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class OverviewCourse(BaseModel):
    id: UUID
    name: str
    status: Literal["active", "inactive"]
    students: list[str]


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
