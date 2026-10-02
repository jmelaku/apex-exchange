from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://apex:apex_local_only@localhost:5432/apex"
    engine_host: str = "localhost"
    engine_port: int = 9001
    risk_url: str = "http://localhost:8001"
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
