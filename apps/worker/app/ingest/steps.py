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

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.worker.app.ingest import db, db_content
from apps.worker.app.ingest.embedding import embed_pending
from apps.worker.app.ingest.tables import extract_tables
from packages.library import storage
from packages.library.chunking import BlockInput, build_chunks, looks_like_heading
from packages.library.formats import SourceKind
from packages.library.parse_models import ImageCase, PageParse
from packages.library.quality import bbox_ok, page_parse_problem
from packages.library.render import RenderError, crop_png, iter_pages
from packages.library.text_first import text_only_pages
from packages.models.budget import EmbeddingBudgetExhausted
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.embeddings import EmbeddingError, VoyageEmbedder
from packages.models.gateway import Transport, run_agent, user_prompt
from packages.models.routing import EmbeddingBudget
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("radbrain.ingest")


@dataclass(slots=True)
class Deps:
    engine: AsyncEngine
    store: storage.ObjectStore
    transport: Transport | None
    embedder: VoyageEmbedder | None
    budget: EmbeddingBudget | None = None


class Deferred(Exception):
    """Work paused (usage window); the task reschedules itself."""


class Continue(Exception):
    """This run hit its page budget; the task re-queues itself immediately.

    Keeping each run short (well under the broker's one-hour visibility
    timeout) stops Redis re-delivering a still-running job, which would parse
    the same pages twice and spend the subscription window twice.
    """


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
    if starting and todo and source["kind"] == SourceKind.PDF.value:
        todo = await _keep_text_pages(deps, job, source, todo)
    for page in todo[:PAGES_PER_RUN]:
        await _parse_page(deps, job, source, page)
    if len(todo) > PAGES_PER_RUN:
        raise Continue
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        first_time = await db.step_status(session, job["id"], "parse_layout") != "succeeded"
        parsed_any = any(p["vision_status"] == "done"
                         for p in await db_content.pages(session, source_id))
        await db.mark_step(session, job, "parse_layout", "succeeded")
        await db.mark_step(session, job, "extract_figures", "succeeded")
    if first_time and parsed_any:
        await _chunk(deps, job)  # vision rewrote the text
    await _embed(deps, job)
    if not first_time:
        return  # reprocess of a finished source: nothing else to redo
    async with db.tenant_tx(deps.engine, tenant_id) as session:
        await db.mark_step(session, job, "knowledge_extraction", "pending")
    # Knowledge slice (ADR 0016): hand the parsed source to radbrain.knowledge_extract.
    from apps.worker.app.knowledge.enqueue import enqueue_knowledge

    enqueue_knowledge(tenant_id, source_id)


async def _keep_text_pages(
    deps: Deps, job: dict[str, Any], source: dict[str, Any], todo: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Text-first routing (ADR 0027): keep the native blocks of pages whose text
    layer is already good, and return only the pages that still need vision."""
    chars = {p["page_no"]: len(p["native_text"] or "") for p in todo}
    keep = text_only_pages(deps.store.get(source["storage_key"]), chars)
    if not keep:
        return todo
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        for page_no in sorted(keep):
            await db_content.set_vision_status(
                session, job["entity_id"], page_no, "done", "native")
    log.info("text_first source=%s native_pages=%s vision_pages=%s",
             job["entity_id"], len(keep), len(todo) - len(keep))
    return [p for p in todo if p["page_no"] not in keep]


async def _parse_page(
    deps: Deps, job: dict[str, Any], source: dict[str, Any], page: dict[str, Any]
) -> None:
    tenant_id, source_id, page_no = job["tenant_id"], job["entity_id"], page["page_no"]
    png = deps.store.get(page["image_key"])
    prompt = user_prompt("page_parse", source_title=str(source["title"]), page_no=str(page_no),
                         native_text=page["native_text"][:12000])
    try:
        parsed, _ = run_agent(deps.transport, "page_parse", prompt,  # type: ignore[arg-type]
                              files=[(f"page-{page_no:05d}.png", png)],
                              accept=lambda p: page_parse_problem(p, page["native_text"]))
    except UsageLimitError as exc:
        raise Deferred from exc
    except ModelCallError:
        log.warning("page_parse failed source=%s page=%s", source_id, page_no)
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            await db_content.set_vision_status(session, source_id, page_no, "failed")
        return
    assert isinstance(parsed, PageParse)
    # A box that is still invalid never reaches provenance or a crop: blocks
    # fall back to a whole-page box, figures without a valid box are dropped.
    figures = [await _figure(deps, job, page_no, png, n, fig.model_dump())
               for n, fig in enumerate(f for f in parsed.figures if bbox_ok(f.bbox))]
    blocks = [
        {"block_no": n, "kind": b.kind, "text": b.text, "origin": "vision",
         "bbox": b.bbox if bbox_ok(b.bbox) else [0.0, 0.0, 1.0, 1.0]}
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
        prompt = user_prompt("image_case", figure_no=str(number), page_no=str(page_no),
                             caption=str(fig["caption"]))
        case, _ = run_agent(deps.transport, "image_case", prompt,  # type: ignore[arg-type]
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
