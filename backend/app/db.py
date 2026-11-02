import logging

from fastapi import HTTPException
from postgrest.exceptions import APIError
from supabase import Client, create_client

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Service-role client. Authorization is enforced in FastAPI. Never call sign_in here.
admin: Client = create_client(settings.supabase_url, settings.supabase_secret_key)


def publishable_client() -> Client:
    """Fresh publishable-key client for one password grant or refresh."""
    return create_client(settings.supabase_url, settings.supabase_publishable_key)


def rows(response) -> list[dict]:
    data = getattr(response, "data", None)
    if not data:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def database_error(exc: APIError, *, conflict: str = "Conflict") -> HTTPException:
    code = str(exc.code or "")
    message = (exc.message or "").lower()
    if code == "P0002" or (code in {"P0001", "P0002"} and "not found" in message):
        return HTTPException(status_code=404, detail="Not found")
    if code == "23505":
        return HTTPException(status_code=409, detail=conflict)
    if code == "23503":
        return HTTPException(status_code=404, detail="Not found")
    if code == "23514":
        return HTTPException(status_code=422, detail="Invalid value")
    logger.error("database error code=%s message=%s", exc.code, exc.message)
    return HTTPException(status_code=500, detail="Database request failed")
