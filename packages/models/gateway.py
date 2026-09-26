"""Run a named agent: versioned prompt + route config + validated output.

This is the only path from application code to a model (hard rule 2). The
concrete model and effort come from ``models.yaml`` and the prompt file; the
output is validated against the agent's Pydantic model before it is returned.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from packages.models import ledger
from packages.models.claude_code import (
    ModelCall,
    ModelCallError,
    ModelResult,
    OwnerApprovalRequired,
    UsageLimitError,
)
from packages.models.claude_stream import DeltaCallback, StreamOutputInvalid, StreamUnsupported
from packages.models.routing import ModelRoutingConfig, load_model_routing_config
from packages.prompts.contracts import PromptFile, load_prompt
from packages.prompts.templating import render

ROOT = Path(__file__).resolve().parents[2]
PROMPT_ROOT = ROOT / "packages" / "prompts"
MODELS_YAML = ROOT / "packages" / "models" / "models.yaml"
log = logging.getLogger("radbrain.models")
# Returns a fixed reason string when an output is not good enough (ADR 0027).
# A reason made with ``soft()`` asks only for a second opinion (ADR 0037).
Accept = Callable[[BaseModel], str | None]
SOFT = "soft:"


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


def user_prompt(name: str, version: int | None = None, **values: str) -> str:
    """Render the user turn from the same prompt version ``run_agent`` will use."""
    template = load_agent(name, version).prompt.user_template
    if template is None:
        raise ValueError(f"agent {name} has no user_template")
    return render(template, values)


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
            effort=effort or (target.effort if override else None) or agent.prompt.effort
            or target.effort or "high",
            system_prompt=agent.prompt.system_prompt,
            user_prompt=user_prompt,
            output_schema=agent.schema,
            files=tuple(files),
            tools=tuple(agent.prompt.tools),
            timeout_s=max(30, route.timeout_ms // 1000),
            backend=target.backend,
            api_key_env=target.api_key_env,
            base_url=target.base_url,
            speed=target.speed,
            requires_approval=target.requires_owner_approval,
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


def _record(
    agent: Agent, call: ModelCall, started: float, status: ledger.Status,
    result: ModelResult | None = None, code: str | None = None,
) -> None:
    """Hand one attempt's ids, numbers, and outcome to the ledger (no content)."""
    tokens_in, tokens_out = ledger.token_counts(result.usage if result else None)
    ledger.emit(ledger.CallRecord(
        agent=agent.key, route=agent.prompt.route, model=call.model, effort=call.effort,
        backend=result.backend if result else call.backend, status=status,
        duration_ms=int((time.monotonic() - started) * 1000), error_code=code,
        input_tokens=tokens_in, output_tokens=tokens_out,
        cost_usd=result.cost_usd if result else None,
    ))


def _failure(exc: ModelCallError) -> ledger.Status:
    return "usage_limit" if isinstance(exc, UsageLimitError) else "error"


def _streamed(
    transport: Transport, agent: Agent, call: ModelCall, on_delta: DeltaCallback,
    accept: Accept | None,
) -> tuple[BaseModel, ModelResult] | None:
    """A streamed, validated, accepted answer, or None when the caller should
    make a plain call.

    Model failures (usage limit, errors) propagate: retrying them would only
    spend more of the usage window.
    """
    stream = getattr(transport, "run_stream", None)
    if stream is None:
        return None
    started = time.monotonic()
    result: ModelResult | None = None
    try:
        result = stream(call, on_delta)
        assert result is not None
        parsed = agent.output_model.model_validate(result.output)
    except StreamUnsupported:
        return None  # no model call was made
    except (StreamOutputInvalid, ValidationError):
        _record(agent, call, started, "error", result, "schema_invalid")
        return None
    except ModelCallError as exc:
        _record(agent, call, started, _failure(exc), None, type(exc).__name__)
        raise
    reason = accept(parsed) if accept else None
    _record(agent, call, started, "ok" if reason is None else "rejected", result,
            None if reason is None else "quality_gate")
    return (parsed, result) if reason is None else None


def run_agent(
    transport: Transport,
    name: str,
    user_prompt: str,
    files: Sequence[tuple[str, bytes]] = (),
    effort: str | None = None,
    accept: Accept | None = None,
    on_delta: DeltaCallback | None = None,
    version: int | None = None,
) -> tuple[BaseModel, ModelResult]:
    """Try each target the transport can serve; the first good output wins.

    A failure, usage limit, schema-invalid output, or an output the ``accept``
    quality gate rejects moves to the next target. The last target's valid
    output is returned even if the gate rejects it (it is the strongest
    available), with a warning. When every target fails, the last error is
    raised (a ``UsageLimitError`` from the last target pauses the caller's job).

    ``on_delta`` receives raw output deltas when the first target's transport
    streams. Deltas are unvalidated: callers may only show them as a labelled
    draft. A streamed answer is validated (and gated) like any other; otherwise
    the ordinary schema-enforced calls follow. ``version`` pins a prompt version
    (default: the newest), so a new version never silently changes an old caller.
    """
    agent = load_agent(name, version)
    served = getattr(transport, "backends", None)
    calls = [c for c in build_calls(agent, user_prompt, files, effort)
             if served is None or c.backend in served]
    if not calls:
        raise ModelCallError(f"{agent.key} has no target this transport can serve")
    if on_delta is not None:
        streamed = _streamed(transport, agent, calls[0], on_delta, accept)
        if streamed is not None:
            return streamed
    return _run_targets(transport, agent, calls, accept)


def owner_approved_fallback() -> bool:
    """The owner's explicit OK for approval-gated targets (set on the host only)."""
    return os.environ.get("BULK_CLAUDE_FALLBACK_APPROVED", "").lower() == "true"


_approved: ContextVar[frozenset[str]] = ContextVar("owner_approved_agents", default=frozenset())


@contextmanager
def owner_approved(*agents: str) -> Iterator[None]:
    """Run these agents straight on their approval-gated target (the owner approved
    these items; the free targets already failed them)."""
    token = _approved.set(_approved.get() | frozenset(agents))
    try:
        yield
    finally:
        _approved.reset(token)


def soft(reason: str) -> str:
    """Mark a gate reason as a second-opinion request: it moves to the next free
    target but never, by itself, to an approval-gated one."""
    return SOFT + reason


def _run_targets(
    transport: Transport, agent: Agent, calls: list[ModelCall], accept: Accept | None
) -> tuple[BaseModel, ModelResult]:
    """Owner flow (ADR 0035/0037): first target, then the next free one on a failure
    or a gate rejection; the approval-gated target only with the owner's OK.

    A usage limit skips that backend's other targets (same quota) and never falls
    through to an approval-gated target: the caller pauses instead.
    """
    forced = agent.prompt.agent in _approved.get()
    if forced:
        calls = [c for c in calls if c.requires_approval] or calls
    last: ModelCallError | None = None
    best: tuple[BaseModel, ModelResult, str] | None = None
    limited: set[str] = set()
    for n, call in enumerate(calls):
        if call.backend in limited:
            continue
        if call.requires_approval and limited and best is None:
            break  # a quota is a pause, never a reason to spend the gated target
        if call.requires_approval and not (forced or owner_approved_fallback()):
            return _awaiting_owner(agent, call, best, last)
        started = time.monotonic()
        result: ModelResult | None = None
        try:
            result = transport.run(call)
            parsed = agent.output_model.model_validate(result.output)
        except ValidationError:
            _record(agent, call, started, "error", result, "schema_invalid")
            last = ModelCallError(f"{agent.key} output failed schema validation")
            continue
        except ModelCallError as exc:
            _record(agent, call, started, _failure(exc), None, type(exc).__name__)
            last = exc
            if isinstance(exc, UsageLimitError):
                limited.add(call.backend)
            continue
        reason = accept(parsed) if accept else None
        if reason is None:
            _record(agent, call, started, "ok", result)
            return parsed, result
        best = (parsed, result, reason)
        if _keep(calls, n, reason, forced):
            log.warning("quality gate agent=%s backend=%s reason=%s action=kept_last",
                        agent.key, call.backend, reason)
            _record(agent, call, started, "ok", result, "gate_kept_last")
            return parsed, result
        log.warning("quality gate agent=%s backend=%s reason=%s action=fallback",
                    agent.key, call.backend, reason)
        _record(agent, call, started, "rejected", result, "quality_gate")
        last = ModelCallError(f"{agent.key} output rejected: {reason}")
    if last is None:
        raise ModelCallError(f"{agent.key}: no target could run")
    raise last


def _keep(calls: list[ModelCall], n: int, reason: str, forced: bool) -> bool:
    """Keep a gate-rejected answer: it came from the last target, or the reason is a
    second-opinion one and the next target needs the owner's approval."""
    if n == len(calls) - 1:
        return True
    gated_next = calls[n + 1].requires_approval and not (forced or owner_approved_fallback())
    return reason.startswith(SOFT) and gated_next


def _awaiting_owner(
    agent: Agent, call: ModelCall, best: tuple[BaseModel, ModelResult, str] | None,
    last: ModelCallError | None,
) -> tuple[BaseModel, ModelResult]:
    """Collect & ask: never call the gated target; hand back the best free answer
    marked for the owner's approval, or pause on a quota, or report the item."""
    log.warning("owner approval required agent=%s backend=%s model=%s",
                agent.key, call.backend, call.model)
    if best is not None:
        parsed, result, reason = best
        result.escalation = reason
        return parsed, result
    if isinstance(last, UsageLimitError):
        raise last  # a quota pause, not a reason to spend the owner's Claude quota
    raise OwnerApprovalRequired(f"{agent.key}: owner approval required for {call.model}")
