"""Dependencies and the model-call wrapper for the knowledge worker."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from apps.worker.app.ops import pausing
from packages.library.storage import ObjectStore
from packages.models.claude_code import ModelCallError, OwnerApprovalRequired, UsageLimitError
from packages.models.gateway import Accept, Transport, run_agent
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.knowledge")
NO_ANSWER = "no_usable_answer"


@dataclass(slots=True)
class KnowledgeDeps:
    engine: AsyncEngine
    transport: Transport | None
    store: ObjectStore | None = None


class Deferred(Exception):
    """Subscription usage window reached; the task reschedules itself."""


def call_agent(
    deps: KnowledgeDeps, name: str, prompt: str, files: Sequence[tuple[str, bytes]] = (),
    accept: Accept | None = None,
) -> BaseModel | None:
    """Run a named agent; None on a model/schema error, Deferred on a pause.

    Only the agent name is logged, never the prompt (hard rule 4).
    """
    return call_agent_result(deps, name, prompt, files, accept)[0]


def call_agent_result(
    deps: KnowledgeDeps, name: str, prompt: str, files: Sequence[tuple[str, bytes]] = (),
    accept: Accept | None = None,
) -> tuple[BaseModel | None, str | None]:
    """Like ``call_agent``, plus why the item waits for the owner's approval (ADR 0037).

    The owner's pause or a quota pause raises Deferred before any call; a quota
    hit pauses every worker until the provider's reset and alerts the owner.
    """
    if deps.transport is None:
        return None, None
    if pausing.paused():
        raise Deferred
    try:
        parsed, result = run_agent(deps.transport, name, prompt, files=files, accept=accept)
    except UsageLimitError as exc:
        pausing.quota_hit(exc)
        raise Deferred from exc
    except OwnerApprovalRequired:
        log.warning("knowledge agent awaits owner agent=%s", name)
        return None, NO_ANSWER
    except ModelCallError:
        log.warning("knowledge agent failed agent=%s", name)
        return None, None
    return parsed, result.escalation


def build_knowledge_deps() -> KnowledgeDeps:
    from apps.worker.app.ingest.runtime import build_deps

    deps = build_deps()
    return KnowledgeDeps(engine=deps.engine, transport=deps.transport, store=deps.store)
