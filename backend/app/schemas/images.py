from pydantic import BaseModel


class UnsplashImageUrls(BaseModel):
    thumb: str
    small: str
    regular: str


class UnsplashUser(BaseModel):
    name: str
    profile_url: str


class UnsplashPhoto(BaseModel):
    id: str
    alt: str
    color: str | None
    blur_hash: str | None
    width: int
    height: int
    urls: UnsplashImageUrls
    user: UnsplashUser
    download_location: str


class UnsplashSearchOut(BaseModel):
    total: int
    total_pages: int
    results: list[UnsplashPhoto]
