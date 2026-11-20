from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.cover_url import (
    clean_color,
    clean_https_url,
    clean_optional_text,
    clean_unsplash_credit_url,
    clean_unsplash_id,
    clean_unsplash_image_url,
    require_text,
)
from app.services.youtube import parse_youtube_video_id


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


class CourseCover(BaseModel):
    image_url: str
    source: Literal["unsplash", "url", "upload", "generated"] | None = None
    alt: str | None = None
    color: str | None = None
    blur_hash: str | None = None
    unsplash_id: str | None = None
    credit_name: str | None = None
    credit_url: str | None = None


class CourseCoverIn(BaseModel):
    source: Literal["unsplash", "url", "generated"]
    unsplash_id: str | None = None
    image_url: str | None = None
    alt: str | None = None
    color: str | None = None
    blur_hash: str | None = None
    credit_name: str | None = None
    credit_url: str | None = None
    download_location: str | None = None

    @field_validator("alt", mode="before")
    @classmethod
    def validate_alt(cls, value: object) -> str | None:
        return clean_optional_text(value, max_len=500, label="Cover alt text")

    @field_validator("blur_hash", mode="before")
    @classmethod
    def validate_blur_hash(cls, value: object) -> str | None:
        return clean_optional_text(value, max_len=64, label="Cover blur hash")

    @field_validator("color", mode="before")
    @classmethod
    def validate_color(cls, value: object) -> str | None:
        return clean_color(value)

    @field_validator("download_location", mode="before")
    @classmethod
    def validate_download_location(cls, value: object) -> str | None:
        return clean_optional_text(value, max_len=2048, label="Cover download location")

    @model_validator(mode="after")
    def validate_source(self) -> "CourseCoverIn":
        if self.source == "unsplash":
            self.image_url = clean_unsplash_image_url(self.image_url)
            self.unsplash_id = clean_unsplash_id(self.unsplash_id)
            self.credit_name = require_text(
                self.credit_name,
                max_len=200,
                label="Cover credit name",
            )
            self.credit_url = clean_unsplash_credit_url(self.credit_url)
            return self
        if self.source == "url":
            self.image_url = clean_https_url(self.image_url, label="Cover image URL")
        else:
            self.image_url = None
        self.unsplash_id = None
        self.credit_name = None
        self.credit_url = None
        self.download_location = None
        return self


class CourseCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_name(value)


class AdminCourseCreate(BaseModel):
    teacher_id: UUID
    name: str
    student_ids: list[UUID]
    cover: CourseCoverIn | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_name(value)


class CourseUpdate(BaseModel):
    name: str | None = None
    status: Literal["active", "inactive"] | None = None
    cover: CourseCoverIn | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_name(value)

    @model_validator(mode="after")
    def at_least_one(self) -> "CourseUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one of name, status, or cover is required")
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
    cover: CourseCover | None


class StudentCourseOut(CourseOut):
    enrolled: bool


class StudentTextBlock(BaseModel):
    id: UUID
    position: int
    kind: Literal["text"]
    body: str


class StudentVideoBlock(BaseModel):
    id: UUID
    position: int
    kind: Literal["video"]
    playback_id: str | None
    youtube_video_id: str | None


StudentBlock = Annotated[
    StudentTextBlock | StudentVideoBlock,
    Field(discriminator="kind"),
]


class TeacherVideoBlock(StudentVideoBlock):
    mux_asset_id: UUID | None
    video_status: Literal["waiting", "asset_created", "ready", "errored"] | None
    video_source: Literal["mux", "youtube"]


TeacherBlock = Annotated[
    StudentTextBlock | TeacherVideoBlock,
    Field(discriminator="kind"),
]


class StudentLesson(BaseModel):
    id: UUID
    lesson_number: int
    title: str
    blocks: list[StudentBlock]


class TeacherLesson(BaseModel):
    id: UUID
    lesson_number: int
    title: str
    blocks: list[TeacherBlock]


class StudentCourseDetail(CourseOut):
    lessons: list[StudentLesson]


class CourseStudent(BaseModel):
    id: UUID
    username: str


class TeacherCourseDetail(CourseOut):
    lessons: list[TeacherLesson]
    students: list[CourseStudent]


class TextBlockIn(BaseModel):
    kind: Literal["text"]
    body: str
    mux_asset_id: UUID | None = None
    youtube_url: str | None = None

    @field_validator("body", mode="before")
    @classmethod
    def validate_body(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Body must be a string")
        return value

    @model_validator(mode="after")
    def no_video(self) -> "TextBlockIn":
        if self.mux_asset_id is not None or self.youtube_url is not None:
            raise ValueError("A text block cannot include a video")
        return self


class VideoBlockIn(BaseModel):
    kind: Literal["video"]
    mux_asset_id: UUID | None = None
    youtube_url: str | None = None

    @field_validator("youtube_url", mode="before")
    @classmethod
    def validate_youtube_url(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("YouTube URL must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Invalid YouTube URL")
        parse_youtube_video_id(cleaned)
        return cleaned

    @model_validator(mode="after")
    def exactly_one_video(self) -> "VideoBlockIn":
        has_mux = self.mux_asset_id is not None
        has_youtube = self.youtube_url is not None
        if has_mux and has_youtube:
            raise ValueError("A video block cannot have both a Mux video and a YouTube video")
        if not has_mux and not has_youtube:
            raise ValueError("A video block needs a Mux video or a YouTube URL")
        return self

    @property
    def youtube_video_id(self) -> str | None:
        if self.youtube_url is None:
            return None
        return parse_youtube_video_id(self.youtube_url)


LessonBlockIn = Annotated[
    TextBlockIn | VideoBlockIn,
    Field(discriminator="kind"),
]


def _require_block_count(blocks: list[LessonBlockIn]) -> None:
    if not 1 <= len(blocks) <= 40:
        raise ValueError("A lesson must have between 1 and 40 blocks")


def _require_lesson_content(blocks: list[LessonBlockIn]) -> None:
    has_video = False
    has_text = False
    for block in blocks:
        if isinstance(block, VideoBlockIn):
            has_video = True
            continue
        if block.body.strip():
            has_text = True
    if not has_video and not has_text:
        raise ValueError("A lesson needs a video or non-blank text")


class LessonCreate(BaseModel):
    title: str
    blocks: list[LessonBlockIn]

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_title(value)

    @model_validator(mode="after")
    def validate_blocks(self) -> "LessonCreate":
        _require_block_count(self.blocks)
        _require_lesson_content(self.blocks)
        return self


class LessonUpdate(BaseModel):
    title: str | None = None
    blocks: list[LessonBlockIn] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_title(value)

    @model_validator(mode="after")
    def at_least_one(self) -> "LessonUpdate":
        if "title" not in self.model_fields_set and "blocks" not in self.model_fields_set:
            raise ValueError("At least one of title or blocks is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title must be between 1 and 160 characters")
        if "blocks" in self.model_fields_set:
            if self.blocks is None:
                raise ValueError("A lesson must have between 1 and 40 blocks")
            _require_block_count(self.blocks)
            _require_lesson_content(self.blocks)
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
