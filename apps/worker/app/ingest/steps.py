"""Resumable, idempotent ingestion steps (spec section 4, ADR 0010).

Order: render pages (native text) -> chunk -> ready (keyword-searchable
within minutes); then the vision pass parses each page with the ``page_parse``
agent, crops and describes radiology figures with ``image_case``, and
re-chunks. Documents are embedded once, on their final text (ADR 0019): while a
vision pass is still pending, embedding waits; unchanged text is reused from
the tenant's embedding cache. Each step records its status in
``job_steps``; a re-run skips succeeded steps and pages already parsed, so a
crash or a subscription usage-limit pause resumes where it stopped.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from apps.worker.app.ingest import db, db_content
from apps.worker.app.ingest.embedding import embed_pending
from apps.worker.app.ingest.tables import extract_tables
from apps.worker.app.ingest.types import Continue, Deferred, Deps
from apps.worker.app.ingest.vision import parse_pages
from packages.library import storage
from packages.library.chunking import BlockInput, build_chunks, looks_like_heading
from packages.library.formats import SourceKind
from packages.library.render import RenderError, iter_pages, office_to_pdf
from packages.library.text_first import text_only_pages
from packages.models.budget import EmbeddingBudgetExhausted
from packages.models.claude_code import ModelCallError
from packages.models.embeddings import EmbeddingError

__all__ = ["Continue", "Deferred", "Deps", "run_ingest"]

log = logging.getLogger("radbrain.ingest")


PAGES_PER_RUN = 25


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
        if source["status"] != "ready":
            # Native-text pass: keyword-searchable quickly. Later runs (vision
            # continuations, reprocess) skip it; the vision pass re-chunks.
            await _chunk(deps, job)
            await _set_ready(deps, job, "ready")
        if not await _awaiting_vision(deps, job):
            await _embed(deps, job)  # final text only; cached text costs nothing
        await _vision_pass(deps, job, source)
    except Deferred:
        return "deferred"
    except Continue:
        return "continue"
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


async def _chunk(deps: Deps, job: dict[str, Any]) -> None:
    tenant_id, source_id = job["tenant_id"], job["entity_id"]
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, "chunk", "running")
        rows = await db_content.blocks(session, source_id)
        chunks = build_chunks(BlockInput(**row) for row in rows)
        total = await db_content.replace_chunks(session, tenant_id, source_id, chunks)
        await db.mark_step(session, job, "chunk", "succeeded", output_ref=f"chunks:{total}")
        tables = await extract_tables(session, tenant_id, source_id)
        await db.mark_step(session, job, "extract_tables", "succeeded",
                           output_ref=f"tables:{tables}")


async def _awaiting_vision(deps: Deps, job: dict[str, Any]) -> bool:
    """True while a vision pass will still rewrite this source's text."""
    if deps.transport is None:
        return False
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        pages = await db_content.pages(session, job["entity_id"])
    return any(p["vision_status"] == "pending" for p in pages)


async def _embed(deps: Deps, job: dict[str, Any]) -> None:
    tenant_id, source_id = job["tenant_id"], job["entity_id"]
    step, status, code, ref = "embed_index", "succeeded", None, None
    if deps.embedder is None or deps.budget is None or not deps.embedder.available():
        status, code = "skipped", "no_embedding_key"
    else:
        try:
            ref = await embed_pending(deps.engine, deps.embedder, deps.budget,
                                      tenant_id, source_id)
        except EmbeddingBudgetExhausted:
            status, code = "skipped", "embedding_budget_exhausted"
        except EmbeddingError:
            # Paid batches are already saved; a later run embeds the rest.
            status, code = "failed", "embedding_error"
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, step, status, code, output_ref=ref)


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
        starting = await db.step_status(session, job["id"], "parse_layout") != "running"
        await db.mark_step(session, job, "parse_layout", "running")
    if starting and todo and source["kind"] in TEXT_FIRST_KINDS:
        todo = await _keep_text_pages(deps, job, source, todo)
    await parse_pages(deps, job, source, todo[:PAGES_PER_RUN])
    if len(todo) > PAGES_PER_RUN:
        raise Continue
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        first_time = await db.step_status(session, job["id"], "parse_layout") != "succeeded"
        parsed_any = any(p["vision_status"] == "done"
                         for p in await db_content.pages(session, source_id))
        await db.mark_step(session, job, "parse_layout", "succeeded")
        await db.mark_step(session, job, "extract_figures", "succeeded")
    # Re-chunk when vision rewrote text: on the first pass, or when this run
    # re-read pages (failed pages retried, or items the owner approved for Opus).
    reread = bool(todo) and not first_time
    if parsed_any and (first_time or reread):
        await _chunk(deps, job)
    await _embed(deps, job)
    if not (first_time or reread):
        return  # reprocess of a finished source: nothing else to redo
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, "knowledge_extraction", "pending")
    # Knowledge slice (ADR 0016): hand the parsed source to radbrain.knowledge_extract.
    from apps.worker.app.knowledge.enqueue import enqueue_knowledge

    enqueue_knowledge(tenant_id, source_id)


TEXT_FIRST_KINDS = {SourceKind.PDF.value, SourceKind.PPTX.value, SourceKind.DOCX.value}


async def _keep_text_pages(
    deps: Deps, job: dict[str, Any], source: dict[str, Any], todo: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Text-first routing (ADR 0027): keep the native blocks of pages whose text
    layer is already good, and return only the pages that still need vision."""
    chars = {p["page_no"]: len(p["native_text"] or "") for p in todo}
    data = deps.store.get(source["storage_key"])
    if source["kind"] != SourceKind.PDF.value:
        # PPTX/DOCX: pdf-inspector reads the same LibreOffice PDF the pages were
        # rendered from, so text-only slides and pages need no model call.
        try:
            data = await asyncio.to_thread(office_to_pdf, data, str(source["kind"]))
        except RenderError:
            return todo
    keep = text_only_pages(data, chars)
    if not keep:
        return todo
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        for page_no in sorted(keep):
            await db_content.set_vision_status(
                session, job["entity_id"], page_no, "done", "native")
    log.info("text_first source=%s native_pages=%s vision_pages=%s",
             job["entity_id"], len(keep), len(todo) - len(keep))
    return [p for p in todo if p["page_no"] not in keep]
