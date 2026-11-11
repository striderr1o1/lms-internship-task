import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException
from jwt.exceptions import PyJWTError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings

_password_hash = PasswordHash((Argon2Hasher(),))
_dummy_hash: str | None = None


def create_access_token(subject: str, email: str) -> tuple[str, int]:
    settings = get_settings()
    ttl = settings.access_token_ttl_seconds
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": subject,
            "email": email,
            "iat": now,
            "exp": now + timedelta(seconds=ttl),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, ttl


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            leeway=30,
            options={
                "require": ["sub", "email"],
                "verify_aud": False,
                "verify_iss": False,
            },
        )
        sub = payload.get("sub")
        email = payload.get("email")
        if not isinstance(sub, str) or not isinstance(email, str) or not email:
            raise PyJWTError("Invalid or expired token")
        uuid.UUID(sub)
    except (PyJWTError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    return payload


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        return False


def dummy_password_hash() -> str:
    # First missing-account sign-in pays the Argon2 hash once. Later checks only verify.
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("northstar-lms-timing-dummy")
    return _dummy_hash
