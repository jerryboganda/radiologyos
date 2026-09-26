"""Queue knowledge extraction after the ingest vision pass (ADR 0016)."""

from __future__ import annotations

import logging
import os
from uuid import UUID

log = logging.getLogger("radbrain.knowledge")


def enqueue_knowledge(tenant_id: UUID, source_id: UUID) -> None:
    """Best-effort: a broker hiccup must not fail an otherwise finished ingest.

    ``KNOWLEDGE_AUTO_EXTRACT=0`` disables the automatic hand-off; extraction can
    still be requested through ``POST /v1/knowledge/sources/{id}/extract``.
    """
    if os.environ.get("KNOWLEDGE_AUTO_EXTRACT", "1") != "1":
        return
    try:
        from apps.worker.app.celery_app import celery_app

        celery_app.send_task(
            "radbrain.knowledge_extract", args=[str(tenant_id), str(source_id), "notes"]
        )
    except Exception:
        log.warning("knowledge enqueue failed source=%s", source_id)
