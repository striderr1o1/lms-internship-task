import uuid

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.core.config import get_settings

_settings = get_settings()
_jwks = PyJWKClient(_settings.jwks_url)


def decode_access_token(token: str) -> dict:
    try:
        signing_key = _jwks.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=_settings.issuer,
            leeway=180,
        )
    except (PyJWTError, OSError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    if payload.get("role") != "authenticated":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    return payload
