"""Voyage AI embeddings over plain HTTPS (ADR 0010).

Uses the already-present httpx dependency instead of a new SDK. The API key is
read from the environment variable named in ``models.yaml`` and never logged.
Text sent here is the tenant's own chunk text; nothing is cached across tenants.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from packages.models.routing import EmbeddingConfig

BATCH = 64


class EmbeddingError(RuntimeError):
    """Embedding failed; the message never contains input text."""


@dataclass(slots=True)
class VoyageEmbedder:
    config: EmbeddingConfig
    timeout_s: float = 60.0
    transport: httpx.BaseTransport | None = None

    @property
    def api_key(self) -> str:
        name = self.config.api_key_env or "VOYAGE_API_KEY"
        return os.environ.get(name, "")

    def available(self) -> bool:
        return self.config.backend == "voyage" and bool(self.api_key)

    def embed(
        self, texts: Sequence[str], input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        if not self.available():
            raise EmbeddingError("embedding provider is not configured")
        vectors: list[list[float]] = []
        base = (self.config.base_url or "https://api.voyageai.com/v1").rstrip("/")
        with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
            for start in range(0, len(texts), BATCH):
                batch = [text[:16000] for text in texts[start : start + BATCH]]
                response = client.post(
                    f"{base}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "input": batch,
                        "model": self.config.model,
                        "input_type": input_type,
                        "output_dimension": self.config.dimensions,
                    },
                )
                if response.status_code != 200:
                    raise EmbeddingError(f"voyage returned HTTP {response.status_code}")
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                vectors.extend([list(map(float, item["embedding"])) for item in data])
        if any(len(v) != self.config.dimensions for v in vectors):
            raise EmbeddingError("embedding dimension mismatch")
        return vectors
