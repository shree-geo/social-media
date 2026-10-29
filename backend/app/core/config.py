from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables only."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "MyLeadToday"
    app_base_url: str = "http://localhost:8080"
    log_level: str = "INFO"

    database_url: PostgresDsn
    database_platform_url: PostgresDsn
    database_migration_url: PostgresDsn | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 10

    redis_url: RedisDsn
    celery_broker_url: RedisDsn

    jwt_secret: str = Field(min_length=32)
    encryption_keys: str
    cors_origins: Annotated[list[str], NoDecode] = []
    cookie_secure: bool = True

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_api_version: str = ""
    meta_webhook_verify_token: str = ""
    meta_login_config_id_messenger: str = ""
    meta_login_config_id_whatsapp: str = ""

    @property
    def meta_configured(self) -> bool:
        """All values needed to talk to Meta (ONBOARDING_AND_CHANNEL_SETUP.md §2) are present."""
        return bool(self.meta_app_id and self.meta_app_secret and self.meta_graph_api_version)

    s3_endpoint: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = ""

    sentry_dsn: str = ""

    bootstrap_admin_email: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
