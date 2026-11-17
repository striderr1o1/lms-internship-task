from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import CurrentUser, require_role
from app.schemas.images import UnsplashSearchOut
from app.services.cover_service import search_unsplash

router = APIRouter(prefix="/images", tags=["images"])


@router.get("/unsplash/search", response_model=UnsplashSearchOut)
def unsplash_search(
    query: str = Query(min_length=1, max_length=120),
    page: int = Query(default=1, ge=1, le=100),
    per_page: int = Query(default=12, ge=1),
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    del user
    cleaned = query.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Query is required")
    return search_unsplash(cleaned, page, min(per_page, 12))
