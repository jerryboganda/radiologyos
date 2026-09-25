from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

from apps.api.app.preview.state import (
    PreviewAudit,
    PreviewBlock,
    PreviewChunk,
    PreviewFigure,
    PreviewJob,
    PreviewPage,
    PreviewSource,
    PreviewState,
    PreviewStep,
)
from apps.worker.app.job_id import IngestStep

_STEP_ORDER = tuple(IngestStep)
_MRN_PATTERN = re.compile(r"\b(?:mrn|medical record)\s*[:#-]?\s*[a-z0-9-]{4,}\b", re.I)
_FIGURE_PATTERN = re.compile(r"^\[\[figure:([a-z0-9_-]+)\]\]$", re.I)


def derive_object_key(tenant_id: UUID, source_id: UUID, part: str) -> str:
    return f"tenants/{tenant_id}/sources/{source_id}/{part}"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _stable_id(tenant_id: UUID, source_id: UUID, kind: str, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"radbrain:{tenant_id}:{source_id}:{kind}:{index}")


def _make_blocks(
    tenant_id: UUID,
    source_id: UUID,
    pages: list[PreviewPage],
    content: str,
) -> tuple[list[PreviewBlock], list[PreviewFigure]]:
    page_chunks = content.split("\f") or [content]
    blocks: list[PreviewBlock] = []
    figures: list[PreviewFigure] = []
    heading_path: list[str] = []
    order = 0
    for page_index, page_text in enumerate(page_chunks, start=1):
        page_id = pages[page_index - 1].id
        paragraphs = _paragraphs(page_text)
        for paragraph_index, paragraph in enumerate(paragraphs):
            lines = paragraph.splitlines()
            marker = _FIGURE_PATTERN.match(lines[0]) if lines else None
            caption = " ".join(lines[1:]).strip() if marker else ""
            if marker and caption:
                paragraph = caption
            if paragraph.startswith("#"):
                heading_path = [
                    part.strip() for part in paragraph.lstrip("#").split(">") if part.strip()
                ]
                paragraph = heading_path[-1] if heading_path else paragraph
            block_id = _stable_id(tenant_id, source_id, "block", order)
            block = PreviewBlock(
                id=block_id,
                tenant_id=tenant_id,
                source_id=source_id,
                page_id=page_id,
                page_no=page_index,
                block_type="heading" if paragraph_index == 0 and heading_path else "paragraph",
                text=paragraph,
                bbox=(0.0, float(order * 24), 800.0, float((order + 1) * 24)),
                heading_path=tuple(heading_path),
                order=order,
            )
            blocks.append(block)
            if marker and caption:
                figures.append(
                    PreviewFigure(
                        id=_stable_id(tenant_id, source_id, "figure", order),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        block_id=block_id,
                        page_no=page_index,
                        image_key=derive_object_key(tenant_id, source_id, f"figures/{order}.png"),
                        caption=caption,
                        modality=marker.group(1),
                    )
                )
            order += 1
    return blocks, figures


def _make_chunks(
    tenant_id: UUID,
    source_id: UUID,
    blocks: Iterable[PreviewBlock],
) -> list[PreviewChunk]:
    chunks: list[PreviewChunk] = []
    current: list[PreviewBlock] = []
    for block in blocks:
        if current and sum(len(item.text.split()) for item in current) >= 400:
            chunks.append(_chunk_from_blocks(tenant_id, source_id, current, len(chunks)))
            current = []
        current.append(block)
    if current:
        chunks.append(_chunk_from_blocks(tenant_id, source_id, current, len(chunks)))
    return chunks


def _chunk_from_blocks(
    tenant_id: UUID,
    source_id: UUID,
    blocks: list[PreviewBlock],
    index: int,
) -> PreviewChunk:
    text = "\n\n".join(block.text for block in blocks)
    digest = hashlib.sha256(text.encode()).hexdigest()
    first = blocks[0]
    last = blocks[-1]
    return PreviewChunk(
        id=_stable_id(tenant_id, source_id, "chunk", index),
        tenant_id=tenant_id,
        source_id=source_id,
        page_no=first.page_no,
        block_start=first.id,
        block_end=last.id,
        text=text,
        heading_path=first.heading_path,
        chunk_hash=digest,
    )


def _job(source: PreviewSource, state: PreviewState, idempotency_key: str) -> PreviewJob:
    steps = {step.value: PreviewStep(step.value) for step in _STEP_ORDER}
    for step in steps.values():
        step.status = "succeeded"
        step.attempts = 1
    for name, reason in (
        (IngestStep.EXTRACT_TABLES.value, "preview_not_implemented"),
        (IngestStep.EMBED_INDEX.value, "provider_gate_blocked"),
        (IngestStep.KNOWLEDGE_EXTRACTION.value, "milestone_m2_preview"),
    ):
        steps[name].status = "skipped"
        steps[name].error_code = reason
    now = state.now()
    return PreviewJob(
        id=state.new_id(),
        tenant_id=source.tenant_id,
        owner_id=source.owner_id,
        source_id=source.id,
        status="succeeded" if source.status == "ready" else "failed",
        idempotency_key=idempotency_key,
        steps=steps,
        created_at=now,
        updated_at=now,
    )


def ingest_source(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    title: str,
    kind: str,
    content: str,
    idempotency_key: str,
) -> tuple[PreviewSource, PreviewJob]:
    if not content.strip():
        raise ValueError("content is required")
    existing_id = state.idempotent_source(tenant_id, idempotency_key)
    if existing_id is not None:
        existing = state.source(tenant_id, existing_id)
        if existing is None:
            raise RuntimeError("idempotency source missing")
        if existing.content != content:
            raise ValueError("idempotency key was reused with different content")
        job = next(item for item in state.jobs(tenant_id) if item.source_id == existing_id)
        return existing, job
    source_id = state.new_id()
    source = PreviewSource(
        id=source_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        title=title.strip(),
        kind=kind,
        content=content,
        status="quarantined" if _MRN_PATTERN.search(content) else "ready",
        page_count=0,
        figure_count=0,
        chunk_count=0,
        object_key=derive_object_key(tenant_id, source_id, "original/source.txt"),
        created_at=state.now(),
    )
    if source.status == "ready":
        page_texts = content.split("\f") or [content]
        pages = [
            PreviewPage(
                id=_stable_id(tenant_id, source_id, "page", index),
                tenant_id=tenant_id,
                source_id=source_id,
                page_no=index,
                width=800,
                height=1000,
                image_key=derive_object_key(tenant_id, source_id, f"pages/{index}.png"),
                has_text_layer=True,
            )
            for index, _ in enumerate(page_texts, start=1)
        ]
        blocks, figures = _make_blocks(tenant_id, source_id, pages, content)
        chunks = _make_chunks(tenant_id, source_id, blocks)
        state.set_content(tenant_id, source_id, pages, blocks, figures, chunks)
        source = replace(
            source,
            page_count=len(pages),
            figure_count=len(figures),
            chunk_count=len(chunks),
        )
    state.add_source(source)
    job = _job(source, state, idempotency_key)
    state.add_job(job)
    state.bind_idempotency(tenant_id, idempotency_key, source.id)
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="source.ingested",
            target_type="source",
            target_id=str(source.id),
            created_at=state.now(),
        )
    )
    return source, job


def search_chunks(
    state: PreviewState,
    tenant_id: UUID,
    query: str,
    limit: int = 10,
) -> list[tuple[PreviewChunk, float]]:
    terms = _tokens(query)
    results: list[tuple[PreviewChunk, float]] = []
    for source in state.sources(tenant_id):
        for chunk in state.source_chunks(tenant_id, source.id):
            overlap = len(terms & _tokens(chunk.text))
            if overlap:
                results.append((chunk, float(overlap) / max(len(terms), 1)))
    return sorted(results, key=lambda item: (-item[1], str(item[0].id)))[:limit]


def search_figures(
    state: PreviewState,
    tenant_id: UUID,
    query: str,
    limit: int = 6,
) -> list[PreviewFigure]:
    terms = _tokens(query)
    results = [
        figure
        for source in state.sources(tenant_id)
        for figure in state.source_figures(tenant_id, source.id)
        if terms & _tokens(f"{figure.caption} {figure.modality}")
    ]
    return results[:limit]
