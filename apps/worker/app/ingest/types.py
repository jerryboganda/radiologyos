"""Shared ingest types: dependencies and the control-flow signals of a run."""

from __future__ import annotations

from dataclasses import dataclass

from packages.library import storage
from packages.models.embeddings import VoyageEmbedder
from packages.models.gateway import Transport
from packages.models.routing import EmbeddingBudget
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(slots=True)
class Deps:
    engine: AsyncEngine
    store: storage.ObjectStore
    transport: Transport | None
    embedder: VoyageEmbedder | None
    budget: EmbeddingBudget | None = None


class Deferred(Exception):
    """Work paused (quota window or the owner's pause); the task reschedules itself."""


class Continue(Exception):
    """This run hit its page budget; the task re-queues itself immediately.

    Keeping each run short (well under the broker's one-hour visibility
    timeout) stops Redis re-delivering a still-running job, which would parse
    the same pages twice and spend the subscription window twice.
    """
