"""Build the ingestion dependencies from the worker environment."""

from __future__ import annotations

import os

from apps.api.app.core.config import get_settings
from apps.worker.app.ingest.db import make_engine
from apps.worker.app.ingest.steps import Deps
from packages.library.storage import S3ObjectStore
from packages.models.embeddings import VoyageEmbedder
from packages.models.gateway import routing_config
from packages.models.transports import default_transport


def object_store() -> S3ObjectStore:
    return S3ObjectStore(
        endpoint=os.environ.get("S3_ENDPOINT", "http://localhost:9000"),
        bucket=os.environ.get("S3_BUCKET", "radbrain"),
        access_key=os.environ.get("S3_ACCESS_KEY", ""),
        secret_key=os.environ.get("S3_SECRET_KEY", ""),
        region=os.environ.get("S3_REGION", "us-east-1"),
    )


def build_deps() -> Deps:
    config = routing_config().embeddings
    return Deps(
        engine=make_engine(),
        store=object_store(),
        # Claude and/or Mistral (ADR 0027); the CLI path comes from Settings (ADR 0032).
        transport=default_transport(get_settings().claude_code_bin),
        embedder=VoyageEmbedder(config.document, config.dimensions) if config else None,
        budget=config.budget if config else None,
    )
