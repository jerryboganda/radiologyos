"""Typed contracts for checked-in model route configuration."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RouteName(StrEnum):
    """Stable application-facing model routes.

    There is deliberately no local route: this project uses online providers
    only, per ADR 0009.
    """

    REASON = "reason"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    VISION = "vision"


class ModelTarget(BaseModel):
    """A deployment target: backend, concrete model, and effort (ADR 0010)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str = Field(min_length=1)
    model: str = Field(min_length=1)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    api_key_env: str | None = None
    base_url: str | None = None


class EmbeddingTarget(BaseModel):
    """One embedding backend: the Voyage API or the local voyage-4-nano service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Literal["voyage", "local", "mock"]
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    base_url: str | None = None


FREE_TIER_TOKENS = 200_000_000


class EmbeddingBudget(BaseModel):
    """Lifetime Voyage token guard (ADR 0019): amber at warn, hard stop at cap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hard_cap_tokens: int = Field(ge=1, le=FREE_TIER_TOKENS)
    warn_tokens: int = Field(ge=1)

    @model_validator(mode="after")
    def warn_below_cap(self) -> EmbeddingBudget:
        if self.warn_tokens >= self.hard_cap_tokens:
            raise ValueError("warn_tokens must be below hard_cap_tokens")
        return self


class EmbeddingConfig(BaseModel):
    """Document and query embedding targets plus the lifetime budget (ADR 0019).

    Both targets are in the Voyage 4 shared embedding space. Every paid call,
    document or query, is metered against ``budget``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimensions: int = Field(ge=1)
    document: EmbeddingTarget
    query: EmbeddingTarget
    budget: EmbeddingBudget


class ModelRoute(BaseModel):
    """Ordered primary target plus explicit fallback route names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    targets: tuple[ModelTarget, ...] = Field(min_length=1)
    fallbacks: tuple[RouteName, ...] = ()
    timeout_ms: int = Field(default=1_000, ge=1, le=1_800_000)
    max_retries: int = Field(default=0, ge=0, le=10)


class AgentTargets(BaseModel):
    """Per-agent target order that overrides its route (ADR 0027).

    Targets are tried in order; a failure, usage limit, or invalid output moves
    to the next one. Concrete names stay in ``models.yaml`` (hard rule 2).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    targets: tuple[ModelTarget, ...] = Field(min_length=1)


class ProviderGate(BaseModel):
    """Release gate for any concrete provider or credential-bearing endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["blocked", "approved"]
    approved_by_adr: str | None = None
    external_egress_allowed: bool = False

    @model_validator(mode="after")
    def require_approval_evidence(self) -> ProviderGate:
        if self.status == "approved" and not self.approved_by_adr:
            raise ValueError("approved provider gate requires an ADR reference")
        if self.status == "blocked" and self.external_egress_allowed:
            raise ValueError("blocked provider gate cannot allow external egress")
        return self


class ModelRoutingConfig(BaseModel):
    """Strict schema for ``packages/models/models.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    config_version: str = Field(min_length=1)
    provider_gate: ProviderGate
    default_backend: str = Field(min_length=1)
    allow_ungrounded_default: Literal[False] = False
    routes: dict[RouteName, ModelRoute]
    agents: dict[str, AgentTargets] = Field(default_factory=dict)
    embeddings: EmbeddingConfig | None = None

    @model_validator(mode="after")
    def require_all_stable_routes(self) -> ModelRoutingConfig:
        missing = set(RouteName) - set(self.routes)
        if missing:
            names = ", ".join(sorted(route.value for route in missing))
            raise ValueError(f"missing required model routes: {names}")
        return self


def require_mock_routes(config: ModelRoutingConfig) -> None:
    """Reject any route that could perform network egress in preview mode."""

    if config.default_backend != "mock" or config.provider_gate.status != "blocked":
        raise ValueError("preview model routes must be blocked and mock-only")
    if config.agents:
        raise ValueError("preview model routes cannot carry agent targets")
    for route in config.routes.values():
        if route.fallbacks:
            raise ValueError("preview model routes cannot have fallbacks")
        for target in route.targets:
            if target.backend != "mock" or target.model != "mock-only":
                raise ValueError("preview model routes must be mock-only")
            if target.api_key_env is not None or target.base_url is not None:
                raise ValueError("preview model routes cannot carry network configuration")


def load_model_routing_config(path: Path) -> ModelRoutingConfig:
    """Load model routes without interpreting environment-specific secrets."""

    with path.open(encoding="utf-8") as config_file:
        payload = yaml.safe_load(config_file)
    return ModelRoutingConfig.model_validate(payload)
