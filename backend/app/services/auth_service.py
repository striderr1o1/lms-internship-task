import hashlib
import secrets
from datetime import datetime, timezone

import psycopg
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.db import database_error, query_one, transaction
from app.schemas.auth import RefreshRequest, SigninRequest, SignupRequest

_PENDING = "Your admin account is waiting for approval"
_INVALID_LOGIN = "Invalid email or password"
_INVALID_REFRESH = "Invalid refresh token"


def signup(body: SignupRequest) -> dict:
    password_hash = hash_password(body.password)
    ttl = get_settings().refresh_token_ttl_seconds
    pending = False
    response: dict | None = None
    try:
        with transaction() as conn:
            if body.role == "admin":
                conn.execute(
                    "select pg_advisory_xact_lock(hashtext('lms_first_admin')::bigint)"
                )
            profile = conn.execute(
                """
                insert into profiles (email, password_hash, username, role)
                values (%s, %s, %s, %s)
                returning id, username, role, email
                """,
                (body.email, password_hash, body.username, body.role),
            ).fetchone()
            if profile is None:
                raise HTTPException(status_code=500, detail="Database request failed")
            admin_status = _insert_role_row(conn, profile["id"], profile["role"])
            if profile["role"] == "admin" and admin_status != "approved":
                pending = True
            else:
                refresh_token = _insert_refresh_token(conn, profile["id"], ttl)
                response = _auth_response(profile, admin_status, refresh_token)
    except psycopg.errors.UniqueViolation as exc:
        raise _from_unique_violation(exc) from exc
    except psycopg.Error as exc:
        raise database_error(exc) from exc

    # The with-block already committed the profile and admins rows.
    if pending:
        raise HTTPException(status_code=403, detail=_PENDING)
    if response is None:
        raise HTTPException(status_code=500, detail="Database request failed")
    return response


def signin(body: SigninRequest) -> dict:
    try:
        profile = query_one(
            """
            select id, username, email, role, password_hash
            from profiles
            where email = %s
            """,
            (body.email,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc

    if profile is None:
        verify_password(body.password, dummy_password_hash())
        raise HTTPException(status_code=401, detail=_INVALID_LOGIN)

    if not verify_password(body.password, profile["password_hash"]):
        raise HTTPException(status_code=401, detail=_INVALID_LOGIN)

    if profile["role"] != body.role:
        raise HTTPException(
            status_code=403,
            detail=f"This account is registered as a {profile['role']}",
        )

    admin_status = None
    if profile["role"] == "admin":
        try:
            admin_row = query_one(
                """
                select status
                from admins
                where profile_id = %s
                """,
                (profile["id"],),
            )
        except psycopg.Error as exc:
            raise database_error(exc) from exc
        admin_status = None if admin_row is None else admin_row["status"]
        if admin_status != "approved":
            raise HTTPException(status_code=403, detail=_PENDING)

    ttl = get_settings().refresh_token_ttl_seconds
    try:
        with transaction() as conn:
            refresh_token = _insert_refresh_token(conn, profile["id"], ttl)
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return _auth_response(profile, admin_status, refresh_token)


def refresh(body: RefreshRequest) -> dict:
    presented = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    ttl = get_settings().refresh_token_ttl_seconds
    reuse = False
    pending = False
    response: dict | None = None
    try:
        with transaction() as conn:
            row = conn.execute(
                """
                select id, profile_id, expires_at, revoked_at
                from refresh_tokens
                where token_hash = %s
                for update
                """,
                (presented,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=401, detail=_INVALID_REFRESH)
            if row["revoked_at"] is not None:
                conn.execute(
                    """
                    update refresh_tokens
                    set revoked_at = now()
                    where profile_id = %s
                      and revoked_at is null
                    """,
                    (row["profile_id"],),
                )
                reuse = True
            elif _refresh_expired(row["expires_at"]):
                raise HTTPException(status_code=401, detail=_INVALID_REFRESH)
            else:
                profile = conn.execute(
                    """
                    select
                      p.id,
                      p.username,
                      p.email,
                      p.role,
                      a.status as admin_status
                    from profiles as p
                    left join admins as a on a.profile_id = p.id
                    where p.id = %s
                    """,
                    (row["profile_id"],),
                ).fetchone()
                if profile is None or not profile["email"]:
                    raise HTTPException(status_code=401, detail=_INVALID_REFRESH)
                if profile["role"] == "admin":
                    admin_status = profile["admin_status"]
                else:
                    admin_status = None
                if profile["role"] == "admin" and admin_status != "approved":
                    pending = True
                else:
                    conn.execute(
                        """
                        update refresh_tokens
                        set revoked_at = now()
                        where id = %s
                        """,
                        (row["id"],),
                    )
                    raw = _insert_refresh_token(conn, profile["id"], ttl)
                    response = _auth_response(profile, admin_status, raw)
    except psycopg.Error as exc:
        raise database_error(exc) from exc

    # Reuse revocation is already committed. Expired tokens never reach this flag.
    if reuse:
        raise HTTPException(status_code=401, detail=_INVALID_REFRESH)
    if pending:
        raise HTTPException(status_code=403, detail=_PENDING)
    if response is None:
        raise HTTPException(status_code=401, detail=_INVALID_REFRESH)
    return response


def _insert_role_row(conn: psycopg.Connection, profile_id: object, role: str) -> str | None:
    if role == "student":
        conn.execute(
            "insert into students (profile_id) values (%s)",
            (profile_id,),
        )
        return None
    if role == "teacher":
        conn.execute(
            "insert into teachers (profile_id) values (%s)",
            (profile_id,),
        )
        return None
    if role != "admin":
        raise HTTPException(status_code=422, detail="Invalid value")

    found = conn.execute(
        """
        select exists (
          select 1
          from admins
          where status = 'approved'
        ) as has_approved
        """
    ).fetchone()
    status = "pending" if found and found["has_approved"] else "approved"
    conn.execute(
        "insert into admins (profile_id, status) values (%s, %s)",
        (profile_id, status),
    )
    return status


def _insert_refresh_token(
    conn: psycopg.Connection, profile_id: object, ttl_seconds: int
) -> str:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    conn.execute(
        """
        insert into refresh_tokens (profile_id, token_hash, expires_at)
        values (%s, %s, now() + make_interval(secs => %s))
        """,
        (profile_id, token_hash, ttl_seconds),
    )
    return raw


def _auth_response(profile: dict, admin_status: str | None, refresh_token: str) -> dict:
    access_token, expires_in = create_access_token(str(profile["id"]), profile["email"])
    if profile["role"] != "admin":
        admin_status = None
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "profile": {
            "id": profile["id"],
            "username": profile["username"],
            "email": profile["email"],
            "role": profile["role"],
            "admin_status": admin_status,
        },
    }


def _from_unique_violation(exc: psycopg.errors.UniqueViolation) -> HTTPException:
    name = exc.diag.constraint_name
    if name == "profiles_email_key":
        return HTTPException(status_code=409, detail="Email is already registered")
    if name == "profiles_username_key":
        return HTTPException(status_code=409, detail="Username is already taken")
    return database_error(exc)


def _refresh_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)
