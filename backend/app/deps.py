from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.db import admin, rows

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
    profile_id = str(payload["sub"])
    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    profile_rows = rows(
        admin.table("profiles")
        .select("id, username, role")
        .eq("id", profile_id)
        .limit(1)
        .execute()
    )
    if not profile_rows:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    profile = profile_rows[0]
    role = profile["role"]

    if role == "student":
        table = "students"
        columns = "id"
    elif role == "teacher":
        table = "teachers"
        columns = "id"
    elif role == "admin":
        table = "admins"
        columns = "id, status"
    else:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    role_rows = rows(
        admin.table(table).select(columns).eq("profile_id", profile_id).limit(1).execute()
    )
    if not role_rows:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    admin_status = role_rows[0].get("status") if role == "admin" else None
    return CurrentUser(
        profile_id=str(profile["id"]),
        username=profile["username"],
        email=email,
        role=role,
        role_row_id=str(role_rows[0]["id"]),
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
