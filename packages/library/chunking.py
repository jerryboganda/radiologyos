"""Heading-aware chunking with page and block provenance.

Chunks target roughly 300-600 tokens (spec section 4), approximated by words.
A heading starts a new chunk, and a chunk never spans more than a few pages, so
every search hit resolves to source -> page -> block for citation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from packages.library.glyphs import tidy

TARGET_WORDS = 320
MAX_WORDS = 460
MAX_PAGE_SPAN = 3


@dataclass(frozen=True, slots=True)
class BlockInput:
    page_no: int
    block_no: int
    kind: str
    text: str


@dataclass(slots=True)
class Chunk:
    chunk_no: int
    page_from: int
    page_to: int
    heading: str
    text: str
    block_refs: list[dict[str, int]] = field(default_factory=list)


def looks_like_heading(text: str, block_no: int) -> bool:
    words = text.split()
    return (
        block_no == 0
        and 0 < len(words) <= 12
        and not text.rstrip().endswith((".", ":", ";", ","))
    )


def build_chunks(blocks: Iterable[BlockInput]) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading = ""
    parts: list[BlockInput] = []

    def flush() -> None:
        nonlocal parts
        body = [p for p in parts if p.text.strip()]
        if body:
            chunks.append(
                Chunk(
                    chunk_no=len(chunks),
                    page_from=min(p.page_no for p in body),
                    page_to=max(p.page_no for p in body),
                    heading=heading,
                    text="\n".join(tidy(p.text.strip()) for p in body),
                    block_refs=[{"page": p.page_no, "block": p.block_no} for p in body],
                )
            )
        parts = []

    for block in blocks:
        words = sum(len(p.text.split()) for p in parts)
        if block.kind == "heading":
            if words >= 40 or not parts:
                flush()
                heading = block.text.strip()[:300]
                parts.append(block)
                continue
        span = block.page_no - (parts[0].page_no if parts else block.page_no)
        if parts and (
            words + len(block.text.split()) > MAX_WORDS
            or span >= MAX_PAGE_SPAN
            or (words >= TARGET_WORDS and block.kind != "list")
        ):
            flush()
        parts.append(block)
    flush()
    return chunks
