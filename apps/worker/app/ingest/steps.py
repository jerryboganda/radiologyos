"""Resumable, idempotent ingestion steps (spec section 4, ADR 0010).

Order: render pages (native text) -> chunk -> embed -> ready, so a source is
searchable within minutes; then the vision pass parses each page with the
``page_parse`` agent, crops and describes radiology figures with
``image_case``, and re-chunks and re-embeds. Each step records its status in
``job_steps``; a re-run skips succeeded steps and pages already parsed, so a
crash or a subscription usage-limit pause resumes where it stopped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.worker.app.ingest import db, db_content
from packages.library import storage
from packages.library.chunking import BlockInput, build_chunks, looks_like_heading
from packages.library.formats import SourceKind
from packages.library.parse_models import ImageCase, PageParse
from packages.library.render import RenderError, crop_png, iter_pages
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.embeddings import EmbeddingError, VoyageEmbedder
from packages.models.gateway import Transport, run_agent
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.ingest")


@dataclass(slots=True)
class Deps:
    engine: AsyncEngine
    store: storage.ObjectStore
    transport: Transport | None
    embedder: VoyageEmbedder | None


class Deferred(Exception):
    """Work paused (usage window); the task reschedules itself."""


async def run_ingest(deps: Deps, tenant_id: UUID, job_id: UUID) -> str:
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        job = await db.load_job(session, job_id)
        if job is None:
            return "missing"
        source = await db.load_source(session, job["entity_id"])
        if source is None:
            await db.set_job_status(session, job_id, "cancelled", "source_deleted")
            return "cancelled"
        await db.set_job_status(session, job_id, "running")
        await db.mark_step(session, job, "upload_dedupe_scan", "succeeded")
    try:
        await _step(deps, job, "render_pages", lambda: _render(deps, job, source))
        await _chunk_and_embed(deps, job)
        await _set_ready(deps, job, "ready")
        await _vision_pass(deps, job, source)
    except Deferred:
        return "deferred"
    except Exception:
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            await db.set_job_status(session, job_id, "failed", "pipeline_error")
            if await db.step_status(session, job_id, "render_pages") != "succeeded":
                await db.set_source_status(session, job["entity_id"], "failed")
        raise
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.set_job_status(session, job_id, "succeeded")
    return "succeeded"


async def _step(deps: Deps, job: dict[str, Any], step: str, work: Any) -> None:
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        if await db.step_status(session, job["id"], step) == "succeeded":
            return
        await db.mark_step(session, job, step, "running")
    try:
        output = await work()
    except (RenderError, ModelCallError, EmbeddingError) as exc:
        async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
            await db.mark_step(session, job, step, "failed", type(exc).__name__)
        raise
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        await db.mark_step(session, job, step, "succeeded", output_ref=output)


async def _render(deps: Deps, job: dict[str, Any], source: dict[str, Any]) -> str:
    tenant_id, source_id = job["tenant_id"], job["entity_id"]
    data = deps.store.get(source["storage_key"])
    kind = SourceKind(source["kind"])
    extension = source["storage_key"].rsplit(".", 1)[-1]
    count = 0
    for page in iter_pages(kind, data, extension):
        key = storage.page_image_key(tenant_id, source_id, page.page_no)
        deps.store.put(key, page.png, "image/png")
        native = [
            {
                "block_no": b.block_no,
                "kind": "heading" if looks_like_heading(b.text, b.block_no) else b.kind,
                "text": b.text, "bbox": b.bbox, "origin": "native",
            }
            for b in page.blocks
        ]
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            await db.upsert_page(session, {
                "tenant_id": tenant_id, "source_id": source_id, "page_no": page.page_no,
                "width": page.width, "height": page.height, "image_key": key,
                "native_text": page.text, "text_origin": "native" if native else "none",
            })
            await db.replace_blocks(session, tenant_id, source_id, page.page_no, native)
        count = page.page_no
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.set_source_status(session, source_id, "processing", page_count=count)
    return f"pages:{count}"


async def _chunk_and_embed(deps: Deps, job: dict[str, Any]) -> None:
    tenant_id, source_id = job["tenant_id"], job["entity_id"]
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, "chunk", "running")
        rows = await db_content.blocks(session, source_id)
        chunks = build_chunks(BlockInput(**row) for row in rows)
        total = await db_content.replace_chunks(session, tenant_id, source_id, chunks)
        await db.mark_step(session, job, "chunk", "succeeded", output_ref=f"chunks:{total}")
        await db.mark_step(session, job, "extract_tables", "skipped", "tables_are_blocks")
    await _embed(deps, job)


async def _embed(deps: Deps, job: dict[str, Any]) -> None:
    tenant_id, source_id = job["tenant_id"], job["entity_id"]
    if deps.embedder is None or not deps.embedder.available():
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            await db.mark_step(session, job, "embed_index", "skipped", "no_embedding_key")
        return
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        pending = await db_content.unembedded_chunks(session, source_id)
    texts = [f"{row['heading']}\n{row['text']}".strip() for row in pending]
    vectors = deps.embedder.embed(texts, "document") if texts else []
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        for row, vector in zip(pending, vectors, strict=True):
            await db_content.set_embedding(session, row["id"], vector, deps.embedder.config.model)
        await db.mark_step(session, job, "embed_index", "succeeded",
                           output_ref=f"embedded:{len(vectors)}")


async def _set_ready(deps: Deps, job: dict[str, Any], status: str) -> None:
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        await db.set_source_status(session, job["entity_id"], status)
        await db.mark_step(session, job, "ready_notify", "succeeded")


async def _vision_pass(deps: Deps, job: dict[str, Any], source: dict[str, Any]) -> None:
    tenant_id, source_id = job["tenant_id"], job["entity_id"]
    if deps.transport is None:
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            for step in ("parse_layout", "extract_figures"):
                await db.mark_step(session, job, step, "skipped", "no_model_transport")
        return
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        todo = [p for p in await db_content.pages(session, source_id)
                if p["vision_status"] == "pending"]
        await db.mark_step(session, job, "parse_layout", "running")
    for page in todo:
        await _parse_page(deps, job, source, page)
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, "parse_layout", "succeeded")
        await db.mark_step(session, job, "extract_figures", "succeeded")
    await _chunk_and_embed(deps, job)
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, "knowledge_extraction", "pending")
    # Knowledge slice (ADR 0016): hand the parsed source to radbrain.knowledge_extract.
    from apps.worker.app.knowledge.enqueue import enqueue_knowledge

    enqueue_knowledge(tenant_id, source_id)


async def _parse_page(
    deps: Deps, job: dict[str, Any], source: dict[str, Any], page: dict[str, Any]
) -> None:
    tenant_id, source_id, page_no = job["tenant_id"], job["entity_id"], page["page_no"]
    png = deps.store.get(page["image_key"])
    prompt = (
        f"Source title: {source['title']}\nPage: {page_no}\n"
        f"Native text layer (may be empty or unordered):\n{page['native_text'][:12000]}"
    )
    try:
        parsed, _ = run_agent(deps.transport, "page_parse", prompt,  # type: ignore[arg-type]
                              files=[(f"page-{page_no:05d}.png", png)])
    except UsageLimitError as exc:
        raise Deferred from exc
    except ModelCallError:
        log.warning("page_parse failed source=%s page=%s", source_id, page_no)
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            await db_content.set_vision_status(session, source_id, page_no, "failed")
        return
    assert isinstance(parsed, PageParse)
    figures = [await _figure(deps, job, page_no, png, n, fig.model_dump())
               for n, fig in enumerate(parsed.figures)]
    blocks = [
        {"block_no": n, "kind": b.kind, "text": b.text, "bbox": b.bbox, "origin": "vision"}
        for n, b in enumerate(parsed.blocks) if b.text.strip()
    ]
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        if blocks:
            await db.replace_blocks(session, tenant_id, source_id, page_no, blocks)
        await db_content.replace_figures(session, tenant_id, source_id, page_no, figures)
        await db_content.set_vision_status(
            session, source_id, page_no, "done", "vision" if blocks else None
        )


async def _figure(
    deps: Deps, job: dict[str, Any], page_no: int, png: bytes, number: int, fig: dict[str, Any]
) -> dict[str, Any]:
    fig = {**fig, "figure_no": number, "image_key": None}
    if not fig.pop("is_radiology_image", False):
        return fig
    try:
        crop = crop_png(png, tuple(fig["bbox"]))
    except RenderError:
        return fig
    key = storage.figure_image_key(job["tenant_id"], job["entity_id"], page_no, number)
    deps.store.put(key, crop, "image/png")
    fig["image_key"] = key
    try:
        case, _ = run_agent(deps.transport, "image_case",  # type: ignore[arg-type]
                            f"Figure {number} on page {page_no}. Caption: {fig['caption']}",
                            files=[("figure.png", crop)])
    except UsageLimitError as exc:
        raise Deferred from exc
    except ModelCallError:
        return fig
    assert isinstance(case, ImageCase)
    fig.update(
        modality=case.modality or fig["modality"], anatomy=case.anatomy or fig["anatomy"],
        description=_case_text(case), findings=case.findings,
    )
    return fig


def _case_text(case: ImageCase) -> str:
    parts = [f"Findings: {'; '.join(case.findings)}" if case.findings else ""]
    if case.impression:
        parts.append(f"Impression: {case.impression} (confidence {case.confidence})")
    if case.differentials:
        parts.append(f"Differentials: {', '.join(case.differentials)}")
    if case.teaching_points:
        parts.append(f"Teaching points: {'; '.join(case.teaching_points)}")
    return "\n".join(p for p in parts if p)
