"""Run a named agent: versioned prompt + route config + validated output.

This is the only path from application code to a model (hard rule 2). The
concrete model and effort come from ``models.yaml`` and the prompt file; the
output is validated against the agent's Pydantic model before it is returned.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from packages.models.claude_code import ModelCall, ModelCallError, ModelResult
from packages.models.routing import ModelRoutingConfig, load_model_routing_config
from packages.prompts.contracts import PromptFile, load_prompt

ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = ROOT / "packages" / "prompts"
MODELS_YAML = ROOT / "packages" / "models" / "models.yaml"


class Transport(Protocol):
    def run(self, call: ModelCall) -> ModelResult: ...


@dataclass(frozen=True, slots=True)
class Agent:
    prompt: PromptFile
    output_model: type[BaseModel]
    schema: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.prompt.agent}/v{self.prompt.version}"


@lru_cache(maxsize=64)
def load_agent(name: str, version: int | None = None) -> Agent:
    folder = PROMPT_ROOT / name
    if version is None:
        versions = sorted(int(p.stem[1:]) for p in folder.glob("v*.yaml"))
        if not versions:
            raise FileNotFoundError(f"no prompt versions for agent {name}")
        version = versions[-1]
    prompt = load_prompt(folder / f"v{version}.yaml")
    if prompt.status != "active" or prompt.output_model is None:
        raise ValueError(f"agent {name} v{version} is not active")
    module_name, _, class_name = prompt.output_model.partition(":")
    output_model = getattr(importlib.import_module(module_name), class_name)
    schema = json.loads((PROMPT_ROOT / prompt.output_schema).read_text(encoding="utf-8"))
    return Agent(prompt, output_model, schema)


@lru_cache(maxsize=1)
def routing_config() -> ModelRoutingConfig:
    return load_model_routing_config(MODELS_YAML)


def build_calls(
    agent: Agent,
    user_prompt: str,
    files: Sequence[tuple[str, bytes]] = (),
    effort: str | None = None,
    config: ModelRoutingConfig | None = None,
) -> list[ModelCall]:
    """Calls in preference order: the agent's own targets (ADR 0027), else its route's."""
    cfg = config or routing_config()
    route = cfg.routes[agent.prompt.route]
    override = cfg.agents.get(agent.prompt.agent)
    targets = override.targets if override else route.targets
    return [
        ModelCall(
            model=target.model,
            effort=effort or agent.prompt.effort or target.effort or "high",
            system_prompt=agent.prompt.system_prompt,
            user_prompt=user_prompt,
            output_schema=agent.schema,
            files=tuple(files),
            tools=tuple(agent.prompt.tools),
            timeout_s=max(30, route.timeout_ms // 1000),
            backend=target.backend,
            api_key_env=target.api_key_env,
            base_url=target.base_url,
        )
        for target in targets
    ]


def build_call(
    agent: Agent,
    user_prompt: str,
    files: Sequence[tuple[str, bytes]] = (),
    effort: str | None = None,
    config: ModelRoutingConfig | None = None,
) -> ModelCall:
    return build_calls(agent, user_prompt, files, effort, config)[0]


def run_agent(
    transport: Transport,
    name: str,
    user_prompt: str,
    files: Sequence[tuple[str, bytes]] = (),
    effort: str | None = None,
) -> tuple[BaseModel, ModelResult]:
    """Try each target the transport can serve; the first valid output wins.

    A failure, usage limit, or schema-invalid output moves to the next target;
    when every target fails, the last error is raised (a ``UsageLimitError``
    from the last target still pauses the caller's job).
    """
    agent = load_agent(name)
    served = getattr(transport, "backends", None)
    calls = [c for c in build_calls(agent, user_prompt, files, effort)
             if served is None or c.backend in served]
    if not calls:
        raise ModelCallError(f"{agent.key} has no target this transport can serve")
    last: ModelCallError | None = None
    for call in calls:
        try:
            result = transport.run(call)
            return agent.output_model.model_validate(result.output), result
        except ValidationError:
            last = ModelCallError(f"{agent.key} output failed schema validation")
        except ModelCallError as exc:
            last = exc
    assert last is not None
    raise last
