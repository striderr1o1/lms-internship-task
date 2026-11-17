from fastapi import APIRouter

from app.schemas.public import FeaturedCourse, PublicStats
from app.services import public_service

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/stats", response_model=PublicStats)
def stats() -> dict:
    return public_service.stats()


@router.get("/courses/featured", response_model=list[FeaturedCourse])
def featured() -> list[dict]:
    return public_service.featured_courses()
