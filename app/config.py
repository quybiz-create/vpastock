"""Cau hinh tap trung cho vpastock backend."""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = True

    DATABASE_URL: str = "sqlite+aiosqlite:///./vpastock.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_REALTIME: int = 60
    CACHE_TTL_CLOSED: int = 3600
    CACHE_TTL_FINANCIAL: int = 86400

    FIREANT_TOKEN: str = ""
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-haiku-4-5-20251001"
    AI_MAX_TOKENS: int = 1024
    AI_CACHE_MINUTES: int = 30

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/vpastock.log"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()