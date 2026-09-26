"""Embedding clients (ADR 0010, ADR 0019).

* ``VoyageEmbedder`` — the paid Voyage API, used only for documents and figure
  descriptions, one token-bounded batch at a time so callers can check the
  budget before each request and save every batch as soon as it is paid for.
* ``LocalEmbedder`` — the free local voyage-4-nano service, used for every
  query and for question-stem dedupe. It shares the Voyage 4 embedding space.

Uses the already-present httpx dependency. The API key is read from the
environment variable named in ``models.yaml`` and never logged; no input text
appears in any log or error message.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from packages.models.routing import EmbeddingTarget

MAX_CHARS = 16_000
MAX_BATCH_TOKENS = 100_000  # voyage-4-large allows 120K per request
MAX_BATCH_TEXTS = 1_000
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
InputType = Literal["document", "query"]
_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


class EmbeddingError(RuntimeError):
    """Embedding failed; the message never contains input text."""


def embed_text(heading: str, text: str) -> str:
    """Normalised text to embed: whitespace collapsed, heading not repeated."""
    body = _BLANK_LINES.sub("\n", _SPACES.sub(" ", text)).strip()
    head = _SPACES.sub(" ", heading).strip()
    if head and not body.startswith(head):
        body = f"{head}\n{body}"
    return body[:MAX_CHARS]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Conservative upper estimate (about 3 characters per token)."""
    return len(text) // 3 + 1


def plan_batches(texts: Sequence[str]) -> list[list[int]]:
    """Group text indexes into requests under the token and count limits."""
    batches: list[list[int]] = []
    current: list[int] = []
    tokens = 0
    for index, text in enumerate(texts):
        cost = estimate_tokens(text)
        if current and (tokens + cost > MAX_BATCH_TOKENS or len(current) >= MAX_BATCH_TEXTS):
            batches.append(current)
            current, tokens = [], 0
        current.append(index)
        tokens += cost
    if current:
        batches.append(current)
    return batches


@dataclass(slots=True)
class BatchResult:
    vectors: list[list[float]]
    tokens: int


@dataclass(slots=True)
class VoyageEmbedder:
    target: EmbeddingTarget
    dimensions: int
    timeout_s: float = 60.0
    transport: httpx.BaseTransport | None = None
    max_attempts: int = 6
    sleep: Callable[[float], None] = field(default=time.sleep)

    @property
    def model(self) -> str:
        return self.target.model

    @property
    def api_key(self) -> str:
        return os.environ.get(self.target.api_key_env or "VOYAGE_API_KEY", "")

    def available(self) -> bool:
        return self.target.backend == "voyage" and bool(self.api_key)

    def embed_batch(self, texts: Sequence[str], input_type: InputType) -> BatchResult:
        """One paid request, retried with backoff on rate limits and 5xx."""
        if not self.available():
            raise EmbeddingError("embedding provider is not configured")
        base = (self.target.base_url or "https://api.voyageai.com/v1").rstrip("/")
        body = {
            "input": [text[:MAX_CHARS] for text in texts],
            "model": self.target.model,
            "input_type": input_type,
            "output_dimension": self.dimensions,
        }
        with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
            for attempt in range(self.max_attempts):
                try:
                    response = client.post(
                        f"{base}/embeddings",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=body,
                    )
                except httpx.TransportError:
                    response = None
                if response is not None and response.status_code == 200:
                    return self._parse(response.json(), len(texts))
                status = response.status_code if response is not None else 0
                if status and status not in RETRY_STATUSES:
                    raise EmbeddingError(f"voyage returned HTTP {status}")
                self.sleep(_backoff(attempt, response))
        raise EmbeddingError("voyage kept failing after retries")

    def _parse(self, payload: dict[str, Any], expected: int) -> BatchResult:
        data: list[dict[str, Any]] = sorted(payload["data"], key=lambda item: item["index"])
        vectors = [list(map(float, item["embedding"])) for item in data]
        if len(vectors) != expected or any(len(v) != self.dimensions for v in vectors):
            raise EmbeddingError("embedding count or dimension mismatch")
        usage = payload.get("usage") or {}
        tokens = int(usage.get("total_tokens", 0)) if isinstance(usage, dict) else 0
        return BatchResult(vectors, tokens)


def _backoff(attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 120.0)
    return float(min(2 ** attempt, 60))


@dataclass(slots=True)
class LocalEmbedder:
    """Client for the local voyage-4-nano service; returns None when unavailable."""

    target: EmbeddingTarget
    dimensions: int
    timeout_s: float = 5.0
    transport: httpx.BaseTransport | None = None

    @property
    def base_url(self) -> str:
        return (os.environ.get("EMBEDDER_URL") or self.target.base_url or "").rstrip("/")

    def embed(self, texts: Sequence[str], input_type: InputType) -> list[list[float]] | None:
        if self.target.backend != "local" or not self.base_url or not texts:
            return None
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
                response = client.post(
                    f"{self.base_url}/embed",
                    json={"texts": [t[:MAX_CHARS] for t in texts], "input_type": input_type},
                )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        vectors = [list(map(float, v)) for v in response.json().get("embeddings", [])]
        if len(vectors) != len(texts) or any(len(v) != self.dimensions for v in vectors):
            return None
        return vectors
