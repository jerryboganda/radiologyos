from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RateRule(BaseModel):
    """A token bucket: ``burst`` requests at once, refilled at ``per_minute``."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    per_minute: float = Field(gt=0, le=10_000)
    burst: int = Field(ge=1, le=10_000)


class BucketRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user: RateRule
    tenant: RateRule


# ADR 0032: expensive endpoints, sized for one person studying hard.
DEFAULT_RATE_LIMITS: dict[str, BucketRule] = {
    "tutor": BucketRule(user=RateRule(per_minute=6, burst=10),
                        tenant=RateRule(per_minute=20, burst=30)),
    "generate": BucketRule(user=RateRule(per_minute=2, burst=5),
                           tenant=RateRule(per_minute=6, burst=10)),
    "upload": BucketRule(user=RateRule(per_minute=30, burst=60),
                         tenant=RateRule(per_minute=60, burst=120)),
    "viva": BucketRule(user=RateRule(per_minute=10, burst=20),
                       tenant=RateRule(per_minute=30, burst=60)),
    "export": BucketRule(user=RateRule(per_minute=0.2, burst=3),
                         tenant=RateRule(per_minute=1, burst=10)),
}


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
    # ADR 0032: per-user and per-tenant token buckets on expensive endpoints.
    # RATE_LIMITS is JSON overriding DEFAULT_RATE_LIMITS per bucket; Redis
    # being down fails open (logged once).
    rate_limit_enabled: bool = True
    rate_limits: dict[str, BucketRule] = Field(default_factory=dict)
    # ADR 0032: /metrics answers only internal callers; with a token set it
    # also demands ``Authorization: Bearer <token>``.
    metrics_token: str = ""
    # ADR 0032 / G35: best-effort Keycloak session revocation on account erase.
    keycloak_admin_url: str = ""
    keycloak_realm: str = "radbrain"
    keycloak_admin_client_id: str = ""
    keycloak_admin_client_secret: str = ""

    def rate_rule(self, bucket: str) -> BucketRule:
        return self.rate_limits.get(bucket) or DEFAULT_RATE_LIMITS[bucket]

    @field_validator("api_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        prefix = value.strip()
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return prefix.rstrip("/") or ""

    @property
    def is_local_development(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
