from fastapi import APIRouter, Depends

from app.deps import CurrentUser, get_current_profile
from app.schemas.auth import (
    AuthResponse,
    ProfileOut,
    RefreshRequest,
    SigninRequest,
    SignupRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(body: SignupRequest) -> dict:
    return auth_service.signup(body)


@router.post("/signin", response_model=AuthResponse)
def signin(body: SigninRequest) -> dict:
    return auth_service.signin(body)


@router.post("/refresh", response_model=AuthResponse)
def refresh(body: RefreshRequest) -> dict:
    return auth_service.refresh(body)


@router.get("/me", response_model=ProfileOut)
def me(user: CurrentUser = Depends(get_current_profile)) -> dict:
    return user.profile()
