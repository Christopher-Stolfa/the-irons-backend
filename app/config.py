from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "The Irons Backend"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False

    api_prefix: str = "/api/v1"

    host: str = "0.0.0.0"
    port: int = 8000

    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    runeprofile_base_url: str = "https://api.runeprofile.com/v1"
    runeprofile_api_key: str | None = None
    runeprofile_user_agent: str = "the-irons-backend"
    runeprofile_username: str | None = None
    runeprofile_timeout_seconds: float = 10.0
    runeprofile_cache_ttl_seconds: float = 3600.0


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached because settings are immutable per-process and reading env
    on every request would be wasteful.
    """
    return Settings()
