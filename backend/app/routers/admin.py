from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import CurrentUser, require_role
from app.schemas.admin import AdminAccount, Overview
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=Overview)
def overview(user: CurrentUser = Depends(require_role("admin"))) -> dict:
    del user
    return admin_service.overview()


@router.get("/admins", response_model=list[AdminAccount])
def list_admins(
    status: Literal["pending", "approved"] = Query(default="pending"),
    user: CurrentUser = Depends(require_role("admin")),
) -> list[dict]:
    del user
    return admin_service.list_admins(status)


@router.post("/admins/{admin_id}/approve", response_model=AdminAccount)
def approve(
    admin_id: UUID,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    del user
    return admin_service.approve(str(admin_id))
