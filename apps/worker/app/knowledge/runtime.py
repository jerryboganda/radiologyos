"""Dependencies and the model-call wrapper for the knowledge worker."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from packages.library.storage import ObjectStore
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import Accept, Transport, run_agent
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.knowledge")


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
    """Run a named agent; None on a model/schema error, Deferred on usage limits.

    Only the agent name is logged, never the prompt (hard rule 4).
    """
    if deps.transport is None:
        return None
    try:
        parsed, _ = run_agent(deps.transport, name, prompt, files=files, accept=accept)
    except UsageLimitError as exc:
        raise Deferred from exc
    except ModelCallError:
        log.warning("knowledge agent failed agent=%s", name)
        return None
    return parsed


def build_knowledge_deps() -> KnowledgeDeps:
    from apps.worker.app.ingest.runtime import build_deps

    deps = build_deps()
    return KnowledgeDeps(engine=deps.engine, transport=deps.transport, store=deps.store)
