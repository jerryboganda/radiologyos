"""Build the ingestion dependencies from the worker environment."""

from __future__ import annotations

import os

from apps.worker.app.ingest.db import make_engine
from apps.worker.app.ingest.steps import Deps
from packages.library.storage import S3ObjectStore
from packages.models.claude_code import ClaudeCodeTransport
from packages.models.embeddings import VoyageEmbedder
from packages.models.gateway import routing_config


def object_store() -> S3ObjectStore:
    return S3ObjectStore(
        endpoint=os.environ.get("S3_ENDPOINT", "http://localhost:9000"),
        bucket=os.environ.get("S3_BUCKET", "radbrain"),
        access_key=os.environ.get("S3_ACCESS_KEY", ""),
        secret_key=os.environ.get("S3_SECRET_KEY", ""),
        region=os.environ.get("S3_REGION", "us-east-1"),
    )


def build_deps() -> Deps:
    transport = ClaudeCodeTransport(os.environ.get("CLAUDE_CODE_BIN", "claude"))
    has_token = bool(
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    )
    config = routing_config().embeddings
    return Deps(
        engine=make_engine(),
        store=object_store(),
        transport=transport if transport.available() and has_token else None,
        embedder=VoyageEmbedder(config.document, config.dimensions) if config else None,
        budget=config.budget if config else None,
    )
