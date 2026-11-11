"""Runtime configuration; credentials are never hard-coded."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    log_level: str = "INFO"
    action_feedbrain_url: str = "http://api:8000"
    # Optional JSON list of action-scoped token grants, without executor IDs.
    # Disabled until explicitly provisioned on the trusted API host.
    action_external_run_tokens: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
