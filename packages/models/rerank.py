"""Voyage reranker client (ADR 0028).

One request reorders the fused (RRF) candidates of a search by relevance to
the query. Uses the already-present httpx dependency; the API key is read
from the environment variable named in ``models.yaml`` and never logged, and
no query or document text appears in any log or error message.

Voyage counts rerank tokens as ``query tokens x documents + document tokens``;
``estimate_tokens`` bounds that before the call so the lifetime cap can be
checked first, and the response's ``usage.total_tokens`` is what is recorded.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from packages.models.embeddings import RETRY_STATUSES, _backoff
from packages.models.embeddings import estimate_tokens as _estimate_text
from packages.models.routing import RerankConfig

MAX_QUERY_CHARS = 2_000
MAX_DOCUMENT_CHARS = 4_000  # the tutor shows at most 4,000 characters of an excerpt
MAX_DOCUMENTS = 100


class RerankError(RuntimeError):
    """Reranking failed; the message never contains query or document text."""


@dataclass(frozen=True, slots=True)
class Ranked:
    index: int
    score: float


@dataclass(frozen=True, slots=True)
class RerankResult:
    ranking: list[Ranked]
    tokens: int


def clip(query: str, documents: Sequence[str]) -> tuple[str, list[str]]:
    """The exact query and documents sent (bounded so tokens stay predictable)."""
    return query[:MAX_QUERY_CHARS], [d[:MAX_DOCUMENT_CHARS] for d in documents[:MAX_DOCUMENTS]]


def estimate_tokens(query: str, documents: Sequence[str]) -> int:
    """Upper estimate of Voyage's rerank count: query x documents + documents."""
    q, docs = clip(query, documents)
    return _estimate_text(q) * len(docs) + sum(_estimate_text(d) for d in docs)


@dataclass(slots=True)
class VoyageReranker:
    config: RerankConfig
    timeout_s: float = 10.0
    transport: httpx.BaseTransport | None = None
    max_attempts: int = 2
    sleep: Callable[[float], None] = field(default=time.sleep)

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def api_key(self) -> str:
        return os.environ.get(self.config.api_key_env or "VOYAGE_API_KEY", "")

    def available(self) -> bool:
        return self.config.backend == "voyage" and bool(self.api_key)

    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> RerankResult:
        """One paid request, retried with backoff on rate limits and 5xx."""
        if not self.available():
            raise RerankError("reranker is not configured")
        q, docs = clip(query, documents)
        if not q.strip() or not docs:
            raise RerankError("nothing to rerank")
        base = (self.config.base_url or "https://api.voyageai.com/v1").rstrip("/")
        body = {"query": q, "documents": docs, "model": self.config.model,
                "top_k": max(1, min(top_k, len(docs))), "truncation": True}
        with httpx.Client(timeout=self.timeout_s, transport=self.transport) as client:
            for attempt in range(self.max_attempts):
                try:
                    response = client.post(
                        f"{base}/rerank",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=body,
                    )
                except httpx.TransportError:
                    response = None
                if response is not None and response.status_code == 200:
                    return _parse(response.json(), len(docs))
                status = response.status_code if response is not None else 0
                if status and status not in RETRY_STATUSES:
                    raise RerankError(f"voyage rerank returned HTTP {status}")
                if attempt + 1 < self.max_attempts:
                    self.sleep(min(_backoff(attempt, response), 5.0))
        raise RerankError("voyage rerank kept failing after retries")


def _parse(payload: dict[str, Any], documents: int) -> RerankResult:
    try:
        data = payload["data"]
        ranking = [Ranked(int(item["index"]), float(item["relevance_score"])) for item in data]
    except (KeyError, TypeError, ValueError) as exc:
        raise RerankError("malformed rerank response") from exc
    indexes = [r.index for r in ranking]
    if len(set(indexes)) != len(indexes) or any(not 0 <= i < documents for i in indexes):
        raise RerankError("rerank response names unknown documents")
    usage = payload.get("usage") or {}
    tokens = int(usage.get("total_tokens", 0)) if isinstance(usage, dict) else 0
    ranking.sort(key=lambda r: r.score, reverse=True)
    return RerankResult(ranking, max(tokens, 0))
