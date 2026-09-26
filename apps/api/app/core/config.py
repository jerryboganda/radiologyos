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
    # ADR 0011: billing is parked; its routes answer 404 unless this is set.
    billing_enabled: bool = False
    # Private object storage (platform MinIO in production, RustFS locally).
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "radbrain"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    signed_url_seconds: int = Field(default=300, ge=30, le=900)
    max_upload_bytes: int = Field(default=300 * 1024 * 1024, ge=1)
    # ADR 0010: models run through Claude Code headless; embeddings via Voyage.
    claude_code_bin: str = "claude"
    # ADR 0013 v2: the semantic grounding judge runs on every tutor answer.
    # Switching it off is an explicit deployment decision; answers are then
    # labelled "not verified" rather than presented as judged.
    tutor_grounding_judge: bool = True
    # ADR 0025: stream labelled draft text while the tutor writes. Drafts are
    # never stored and are always replaced by the judged answer; off = the
    # stream carries progress only and every call is schema-enforced JSON.
    # Off by default: drafts are uncited text (CLAUDE.md "Never"), so turning
    # them on is the owner's explicit, reviewed decision.
    tutor_stream_drafts: bool = False
    # Shared with the web server only; signs backend-for-frontend assertions.
    web_api_secret: str = ""
    library_enabled: bool = True
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
        if not self.preview_enabled or self.is_local_development:
            return self
        # ADR 0009: the non-release preview surface ships to production, but
        # only behind authentication. principal_from_request already refuses
        # header-based identity outside local development, so the only way in is
        # a verified OIDC bearer token whose membership is resolved from the
        # database. Requiring an explicit JWKS URL means preview cannot be
        # switched on for a host that has no identity provider wired up, where it
        # would be unreachable rather than merely unauthenticated.
        if not self.oidc_jwks_url:
            raise ValueError(
                "preview outside local development requires a configured "
                "OIDC_JWKS_URL so it is only reachable behind authentication"
            )
        return self

    @property
    def is_local_development(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
