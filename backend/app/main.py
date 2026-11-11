from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db import close_pool, open_pool
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.student import router as student_router
from app.routers.teacher import router as teacher_router
from app.routers.webhooks import router as webhook_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    open_pool()
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="Northstar LMS", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router, prefix="/api")
app.include_router(student_router, prefix="/api")
app.include_router(teacher_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(webhook_router, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _validation_detail(exc)})


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


def _validation_detail(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid request"
    first = errors[0]
    message = str(first.get("msg") or "Invalid request")
    prefix = "Value error, "
    if message.startswith(prefix):
        message = message[len(prefix) :]
    location = [
        str(part)
        for part in first.get("loc", [])
        if part not in {"body", "query", "path"}
    ]
    if location:
        return f"{'.'.join(location)}: {message}"
    return message
