from dataclasses import dataclass
from uuid import UUID

import psycopg
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.db import database_error, query_one

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    profile_id: str
    username: str
    email: str
    role: str
    role_row_id: str
    admin_status: str | None

    def profile(self) -> dict:
        return {
            "id": self.profile_id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "admin_status": self.admin_status,
        }


def get_current_profile(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    payload = decode_access_token(credentials.credentials)
    try:
        profile_id = str(UUID(str(payload.get("sub"))))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    try:
        row = query_one(
            """
            select
              p.id,
              p.username,
              p.email,
              p.role,
              s.id as student_id,
              t.id as teacher_id,
              a.id as admin_id,
              a.status as admin_status
            from profiles as p
            left join students as s on s.profile_id = p.id
            left join teachers as t on t.profile_id = p.id
            left join admins as a on a.profile_id = p.id
            where p.id = %s
            """,
            (profile_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    role = row["role"]
    if role == "student":
        role_row_id = row["student_id"]
        admin_status = None
    elif role == "teacher":
        role_row_id = row["teacher_id"]
        admin_status = None
    elif role == "admin":
        role_row_id = row["admin_id"]
        admin_status = row["admin_status"]
    else:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if role_row_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return CurrentUser(
        profile_id=str(row["id"]),
        username=row["username"],
        email=row["email"],
        role=role,
        role_row_id=str(role_row_id),
        admin_status=admin_status,
    )


def require_role(role: str):
    def dependency(user: CurrentUser = Depends(get_current_profile)) -> CurrentUser:
        if user.role != role:
            raise HTTPException(status_code=403, detail="Forbidden")
        if role == "admin" and user.admin_status != "approved":
            raise HTTPException(
                status_code=403,
                detail="Your admin account is waiting for approval",
            )
        return user

    return dependency
