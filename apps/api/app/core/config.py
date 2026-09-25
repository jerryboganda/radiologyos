from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    debug: bool = False
    api_prefix: str = "/v1"
    database_url: str = "postgresql+asyncpg://localhost/radbrain"
    database_migrator_url: str = "postgresql+asyncpg://localhost/radbrain"
    redis_url: str = "redis://localhost:6379/0"
    oidc_issuer: str = "http://localhost:8080/realms/radbrain"
    oidc_jwks_url: str | None = None
    oidc_client_id: str = "radbrain-web"
    oidc_audience: str = "radbrain-api"
    oidc_client_secret: str = "change-me"
    cookie_secure: bool = False
    embed_dim: int = Field(default=1024, ge=1)
    image_embed_dim: int = Field(default=1152, ge=1)
    pipeline_version: int = Field(default=1, ge=1)
    models_config_path: Path = Path("packages/models/models.yaml")
    allow_ungrounded_default: bool = False
    preview_enabled: bool = False
    core_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    @field_validator("api_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        prefix = value.strip()
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return prefix.rstrip("/") or ""

    @model_validator(mode="after")
    def validate_preview_mode(self) -> Settings:
        if self.preview_enabled and not self.is_local_development:
            raise ValueError("preview mode is restricted to local and test environments")
        return self

    @property
    def is_local_development(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
