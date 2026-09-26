"""Near-duplicate rules for generated stems (spec section 8, step 5). Pure code.

With embeddings configured, a new stem whose cosine similarity to one of the
user's existing question stems is at least ``EMBEDDING_THRESHOLD`` is a
duplicate. Without embeddings, the fallback is PostgreSQL ``pg_trgm``
``similarity()`` over normalised stems, at least ``TRIGRAM_THRESHOLD``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

EMBEDDING_THRESHOLD = 0.92
TRIGRAM_THRESHOLD = 0.9
Method = Literal["embedding", "trigram"]
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class DuplicateHit:
    question_id: UUID
    similarity: float
    method: Method


def normalize_stem(text: str) -> str:
    """Lower-case, punctuation to spaces, whitespace collapsed (mirrors the migration)."""
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def threshold(method: Method) -> float:
    return EMBEDDING_THRESHOLD if method == "embedding" else TRIGRAM_THRESHOLD


def is_duplicate(similarity: float | None, method: Method) -> bool:
    return similarity is not None and similarity >= threshold(method)


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
