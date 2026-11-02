from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str
    supabase_secret_key: str = ""
    supabase_publishable_key: str = ""
    frontend_origin: str = "http://localhost:5173"
    mux_token_id: str = ""
    mux_token_secret: str = ""
    mux_webhook_secret: str = ""

    @property
    def issuer(self) -> str:
        return self.supabase_url.rstrip("/") + "/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
