import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupRequest(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9_]{3,32}$")
    email: str
    password: str = Field(min_length=8, max_length=72)
    role: Literal["student", "teacher", "admin"]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("Email is invalid")
        return normalized

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class SigninRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=72)
    role: Literal["student", "teacher", "admin"]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("Email is invalid")
        return normalized

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ProfileOut(BaseModel):
    id: UUID
    username: str
    email: str
    role: Literal["student", "teacher", "admin"]
    admin_status: Literal["pending", "approved"] | None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int
    profile: ProfileOut
