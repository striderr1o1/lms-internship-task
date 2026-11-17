from uuid import UUID

from pydantic import BaseModel

from app.schemas.courses import CourseCover


class PublicStats(BaseModel):
    courses: int
    lessons: int
    learners: int


class FeaturedCourse(BaseModel):
    id: UUID
    name: str
    cover: CourseCover | None
    lesson_count: int
    teacher_display_name: str
