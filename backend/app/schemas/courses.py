from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= 120:
        raise ValueError("Name must be between 1 and 120 characters")
    return cleaned


def _clean_title(value: str) -> str:
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= 160:
        raise ValueError("Title must be between 1 and 160 characters")
    return cleaned


class CourseCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_name(value)


class CourseUpdate(BaseModel):
    name: str | None = None
    status: Literal["active", "inactive"] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_name(value)

    @model_validator(mode="after")
    def at_least_one(self) -> "CourseUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one of name or status is required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name must be between 1 and 120 characters")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Status must be active or inactive")
        return self


class CourseOut(BaseModel):
    id: UUID
    name: str
    status: Literal["active", "inactive"]
    created_at: str
    teacher_username: str
    lesson_count: int


class StudentCourseOut(CourseOut):
    enrolled: bool


class StudentLesson(BaseModel):
    id: UUID
    lesson_number: int
    title: str
    body: str
    playback_id: str | None


class TeacherLesson(StudentLesson):
    mux_asset_id: UUID | None
    video_status: Literal["waiting", "asset_created", "ready", "errored"] | None


class StudentCourseDetail(CourseOut):
    lessons: list[StudentLesson]


class TeacherCourseDetail(CourseOut):
    lessons: list[TeacherLesson]


class LessonCreate(BaseModel):
    title: str
    body: str = ""
    mux_asset_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_title(value)

    @field_validator("body", mode="before")
    @classmethod
    def validate_body(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("Body must be a string")
        return value


class LessonUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    mux_asset_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_title(value)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value

    @model_validator(mode="after")
    def at_least_one(self) -> "LessonUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one of title, body, or mux_asset_id is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title must be between 1 and 160 characters")
        if "body" in self.model_fields_set and self.body is None:
            raise ValueError("Body must be a string")
        return self


class EnrollmentOut(BaseModel):
    course_id: UUID
    enrolled_at: str


class UploadOut(BaseModel):
    id: UUID
    upload_url: str


class VideoOut(BaseModel):
    id: UUID
    status: Literal["waiting", "asset_created", "ready", "errored"]
    playback_id: str | None
