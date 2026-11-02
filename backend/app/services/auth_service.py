import logging

from fastapi import HTTPException
from supabase_auth.errors import (
    AuthApiError,
    AuthError,
    AuthInvalidCredentialsError,
    AuthRetryableError,
    AuthSessionMissingError,
)

from app.db import admin, publishable_client, rows
from app.schemas.auth import RefreshRequest, SigninRequest, SignupRequest

logger = logging.getLogger(__name__)

_PENDING = "Your admin account is waiting for approval"


def signup(body: SignupRequest) -> dict:
    taken = rows(
        admin.table("profiles").select("id").eq("username", body.username).limit(1).execute()
    )
    if taken:
        raise HTTPException(status_code=409, detail="Username is already taken")

    try:
        created = admin.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
                "app_metadata": {"role": body.role, "username": body.username},
            }
        )
    except AuthApiError as exc:
        if _is_duplicate_email(exc):
            raise HTTPException(status_code=409, detail="Email is already registered") from exc
        if _is_duplicate_username(exc):
            raise HTTPException(status_code=409, detail="Username is already taken") from exc
        logger.warning("create_user failed code=%s", exc.code)
        raise HTTPException(status_code=400, detail="Account could not be created") from exc

    user = created.user
    if user is None or not user.id:
        raise HTTPException(status_code=400, detail="Account could not be created")
    user_id = str(user.id)

    profile_rows = rows(
        admin.table("profiles")
        .select("id, username, role")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not profile_rows:
        _delete_auth_user(user_id)
        raise HTTPException(status_code=400, detail="Account could not be created")

    profile = profile_rows[0]
    admin_status = _admin_status(user_id, profile["role"])
    if profile["role"] == "admin" and admin_status != "approved":
        raise HTTPException(status_code=403, detail=_PENDING)

    session = _password_session(body.email, body.password)
    email = user.email or body.email
    return _payload(session, profile, email, admin_status)


def signin(body: SigninRequest) -> dict:
    client = publishable_client()
    try:
        result = client.auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except (AuthApiError, AuthInvalidCredentialsError) as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    except AuthRetryableError as exc:
        raise HTTPException(
            status_code=503, detail="Authentication service is unavailable"
        ) from exc

    if result.session is None or result.user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    profile = _profile_or_401(str(result.user.id), "Invalid email or password")
    if profile["role"] != body.role:
        raise HTTPException(
            status_code=403,
            detail=f"This account is registered as a {profile['role']}",
        )
    admin_status = _admin_status(str(profile["id"]), profile["role"])
    if profile["role"] == "admin" and admin_status != "approved":
        raise HTTPException(status_code=403, detail=_PENDING)

    email = result.user.email or body.email
    return _payload(result.session, profile, email, admin_status)


def refresh(body: RefreshRequest) -> dict:
    client = publishable_client()
    try:
        result = client.auth.refresh_session(body.refresh_token)
    except (AuthApiError, AuthInvalidCredentialsError, AuthSessionMissingError) as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    except AuthRetryableError as exc:
        raise HTTPException(
            status_code=503, detail="Authentication service is unavailable"
        ) from exc

    if result.session is None or result.user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    profile = _profile_or_401(str(result.user.id), "Invalid refresh token")
    admin_status = _admin_status(str(profile["id"]), profile["role"])
    if profile["role"] == "admin" and admin_status != "approved":
        raise HTTPException(status_code=403, detail=_PENDING)

    email = result.user.email or ""
    if not email:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return _payload(result.session, profile, email, admin_status)


def _password_session(email: str, password: str):
    client = publishable_client()
    try:
        result = client.auth.sign_in_with_password({"email": email, "password": password})
    except (AuthApiError, AuthInvalidCredentialsError) as exc:
        raise HTTPException(status_code=400, detail="Could not start a session") from exc
    except AuthRetryableError as exc:
        raise HTTPException(
            status_code=503, detail="Authentication service is unavailable"
        ) from exc
    if result.session is None:
        raise HTTPException(status_code=400, detail="Could not start a session")
    return result.session


def _profile_or_401(user_id: str, detail: str) -> dict:
    found = rows(
        admin.table("profiles")
        .select("id, username, role")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not found:
        raise HTTPException(status_code=401, detail=detail)
    return found[0]


def _admin_status(profile_id: str, role: str) -> str | None:
    if role != "admin":
        return None
    found = rows(
        admin.table("admins").select("status").eq("profile_id", profile_id).limit(1).execute()
    )
    if not found:
        return None
    return found[0]["status"]


def _payload(session, profile: dict, email: str, admin_status: str | None) -> dict:
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": "bearer",
        "expires_in": session.expires_in,
        "profile": {
            "id": profile["id"],
            "username": profile["username"],
            "email": email,
            "role": profile["role"],
            "admin_status": admin_status,
        },
    }


def _delete_auth_user(user_id: str) -> None:
    try:
        admin.auth.admin.delete_user(user_id)
    except AuthError:
        logger.warning("failed to roll back auth user %s", user_id)


def _is_duplicate_email(exc: AuthApiError) -> bool:
    code = (exc.code or "").lower()
    message = (exc.message or "").lower()
    if code in {"email_exists", "user_already_exists"}:
        return True
    return "already" in message and ("email" in message or "registered" in message)


def _is_duplicate_username(exc: AuthApiError) -> bool:
    text = f"{exc.message or ''} {exc.code or ''}".lower()
    return "profiles_username" in text or ("username" in text and "duplicate" in text)
