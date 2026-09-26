"""Vision pass units: read a page, crop and describe its radiology figures.

Owner flow (ADR 0035/0037): GPT-6 Luna max, then Sol high when Luna fails or a
quality gate finds its answer ambiguous; Claude Opus 5.5 high only for items the
owner approved. An item neither GPT model answers well is saved for approval
("collect & ask") and the run moves on. Each page is saved as soon as it is
read, and the owner's pause or a quota pause stops between pages, so a run
resumes exactly where it stopped.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.worker.app.ingest import db, db_content
from apps.worker.app.ingest.types import Deferred, Deps
from apps.worker.app.ops import escalations, pausing
from packages.library import storage
from packages.library.figure_context import (
    build_context,
    case_text,
    figure_problem,
    impression_origin,
    neighbour_pages,
)
from packages.library.parse_models import PageParse, SourceImageCase
from packages.library.quality import bbox_ok, page_parse_problem
from packages.library.render import RenderError, crop_png
from packages.models.claude_code import ModelCallError, OwnerApprovalRequired, UsageLimitError
from packages.models.gateway import owner_approved, run_agent, user_prompt

log = logging.getLogger("radbrain.ingest")
PAGE, FIGURE = "page_parse", "image_case"
NO_ANSWER = "no_usable_answer"


async def parse_pages(
    deps: Deps, job: dict[str, Any], source: dict[str, Any], pages: list[dict[str, Any]]
) -> None:
    """Read pages in order; stop between pages when processing is paused."""
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        approved = {agent: await escalations.approved_units(session, job["entity_id"], agent)
                    for agent in (PAGE, FIGURE)}
    for page in pages:
        if pausing.paused():
            raise Deferred
        unit = f"page:{page['page_no']}"
        agents = [agent for agent in (PAGE, FIGURE) if unit in approved[agent]]
        with owner_approved(*agents):  # only the owner's approved items reach Opus
            await parse_page(deps, job, source, page)
        if agents:
            async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
                for agent in agents:
                    await escalations.mark_done(session, job["entity_id"], agent, unit)


async def _model(
    deps: Deps, job: dict[str, Any], agent: str, unit: str, prompt: str, **kwargs: Any
) -> Any:
    """One gated model call; None when the item was saved for the owner's approval."""
    try:
        parsed, result = run_agent(deps.transport, agent, prompt, **kwargs)  # type: ignore[arg-type]
    except UsageLimitError as exc:
        pausing.quota_hit(exc)
        raise Deferred from exc
    except OwnerApprovalRequired:
        await escalations.escalate(deps.engine, job["tenant_id"], job["entity_id"], agent,
                                   unit, NO_ANSWER)
        return None
    except ModelCallError:
        log.warning("%s failed source=%s unit=%s", agent, job["entity_id"], unit)
        return None
    if result.escalation:
        await escalations.escalate(deps.engine, job["tenant_id"], job["entity_id"], agent,
                                   unit, result.escalation)
    return parsed


async def parse_page(
    deps: Deps, job: dict[str, Any], source: dict[str, Any], page: dict[str, Any]
) -> None:
    tenant_id, source_id, page_no = job["tenant_id"], job["entity_id"], page["page_no"]
    png = deps.store.get(page["image_key"])
    prompt = user_prompt(PAGE, source_title=str(source["title"]), page_no=str(page_no),
                         native_text=page["native_text"][:12000])
    parsed = await _model(deps, job, PAGE, f"page:{page_no}", prompt,
                          files=[(f"page-{page_no:05d}.png", png)],
                          accept=lambda p: page_parse_problem(p, page["native_text"]))
    if parsed is None:
        async with db.tenant_tx(deps.engine, tenant_id) as session:
            await db_content.set_vision_status(session, source_id, page_no, "failed")
        return
    assert isinstance(parsed, PageParse)
    # A box that is still invalid never reaches provenance or a crop: blocks
    # fall back to a whole-page box, figures without a valid box are dropped.
    boxed = [f for f in parsed.figures if bbox_ok(f.bbox)]
    context = await _figure_context(deps, job, page_no, parsed) if boxed else ""
    figures = [await _figure(deps, job, page_no, png, n, fig.model_dump(), context)
               for n, fig in enumerate(boxed)]
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


async def _figure_context(
    deps: Deps, job: dict[str, Any], page_no: int, parsed: PageParse
) -> str:
    """This page's freshly parsed text plus the next page's text (ADR 0036)."""
    async with db.tenant_tx(deps.engine, job["tenant_id"]) as session:
        texts = await db_content.page_texts(session, job["entity_id"], *neighbour_pages(page_no))
    own = " ".join(b.text for b in parsed.blocks if b.text.strip())
    return build_context(page_no, {**texts, page_no: own or texts.get(page_no, "")})


async def _figure(
    deps: Deps, job: dict[str, Any], page_no: int, png: bytes, number: int,
    fig: dict[str, Any], context: str,
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
    prompt = user_prompt(FIGURE, 2, figure_no=str(number), page_no=str(page_no),
                         caption=str(fig["caption"]), context=context)
    case = await _model(deps, job, FIGURE, f"page:{page_no}", prompt,
                        files=[("figure.png", crop)], version=2,
                        accept=lambda c: figure_problem(c, context))
    if case is None:
        return fig
    assert isinstance(case, SourceImageCase)
    origin, quote = impression_origin(case, context)
    fig.update(
        modality=case.modality or fig["modality"], anatomy=case.anatomy or fig["anatomy"],
        description=case_text(case, origin), findings=case.findings,
        impression_origin=origin if case.impression.strip() else None, source_quote=quote,
    )
    return fig
