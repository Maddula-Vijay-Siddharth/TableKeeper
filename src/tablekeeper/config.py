from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://tablekeeper:tablekeeper@localhost:5432/tablekeeper"
    idempotency_ttl_hours: int = 48

    model_config = SettingsConfigDict(env_prefix="TABLEKEEPER_", env_file=".env", extra="ignore")


settings = Settings()
