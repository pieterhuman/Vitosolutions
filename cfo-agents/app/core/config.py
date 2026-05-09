from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", case_sensitive=False, extra="ignore"
    )

    # App
    app_env: Literal["local", "staging", "prod"] = Field("local", alias="CFO_APP_ENV")
    demo_mode: bool = Field(True, alias="CFO_DEMO_MODE")
    log_level: str = Field("INFO", alias="CFO_LOG_LEVEL")
    secret_key: str = Field("change-me-change-me-change-me-32", alias="CFO_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", alias="CFO_JWT_ALGORITHM")
    jwt_ttl_min: int = Field(60, alias="CFO_JWT_TTL_MIN")

    # DB
    database_url: str = Field(
        "postgresql+psycopg://cfo:cfo@localhost:5432/cfo_agents",
        alias="CFO_DATABASE_URL",
    )

    # Anthropic
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field("claude-sonnet-4-6", alias="CFO_CLAUDE_MODEL")

    # Xero
    xero_client_id: str = Field("", alias="XERO_CLIENT_ID")
    xero_client_secret: str = Field("", alias="XERO_CLIENT_SECRET")
    xero_redirect_uri: str = Field(
        "http://localhost:8000/api/xero/callback", alias="XERO_REDIRECT_URI"
    )
    xero_scopes: str = Field(
        "offline_access accounting.transactions accounting.contacts "
        "accounting.reports.read accounting.settings",
        alias="XERO_SCOPES",
    )

    # n8n
    n8n_webhook_base: str = Field("", alias="N8N_WEBHOOK_BASE")
    n8n_webhook_secret: str = Field("", alias="N8N_WEBHOOK_SECRET")

    # Approval
    auto_approve_threshold: float = Field(0.0, alias="CFO_AUTO_APPROVE_THRESHOLD")


@lru_cache
def get_settings() -> Settings:
    return Settings()
