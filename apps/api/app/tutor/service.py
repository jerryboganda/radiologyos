"""One tutor ask, in phases that never hold a database transaction during a model call.

1. ``load`` (database): the thread (404 if not the caller's), its rolling memory,
   the attached image row (404 if not the caller's), and the Reader page label.
2. ``read_attached`` (threadpool): the cached AI reading of the image, or a new
   one from the vision agent.
3. ``retrieve`` (database): hybrid search on the question plus the reading's
   key terms; with a Reader focus, that page's chunks and figures come first.
4. ``answer_work`` (threadpool): fold old turns into the rolling summary when
   the history exceeds its budget, then answer, ground, and judge.
5. ``persist`` (database): the exchange, the image reading cache, and memory.

Only ids, counts, and outcomes are logged (hard rule 4).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.api.app.api.library import query_vector
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import set_database_tenant
from apps.api.app.library import search
from apps.api.app.observability import logger
from apps.api.app.security.principal import Principal
from apps.api.app.tutor import images, repo
from apps.api.app.tutor.contracts import AskRequest, AskResponse
from fastapi import HTTPException
from packages.library.parse_models import ImageCase
from packages.library.storage import ObjectStore
from packages.models.claude_code import ModelCallError
from packages.models.gateway import Transport, load_agent
from packages.tutor.grounding import Excerpt, FigureExcerpt, excerpts_from_hits, figures_from_hits
from packages.tutor.image import IMAGE_AGENT, read_image, retrieval_text
from packages.tutor.memory import MemoryState, MemoryUpdate, fold_memory, plan_memory
from packages.tutor.models import GroundedAnswer, JudgeStats
from packages.tutor.orchestrator import answer_question
from packages.tutor.prompts import Context
from sqlalchemy.ext.asyncio import AsyncSession

RETRIEVE = 8
FIGURE_CANDIDATES = 12
FOCUS_CHUNKS = 4
FOCUS_FIGURES = 4
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")
Report = Callable[[object], None]


@dataclass(frozen=True, slots=True)
class Loaded:
    memory: MemoryState
    image: dict[str, Any] | None
    reading_label: str


@dataclass(frozen=True, slots=True)
class Prepared:
    loaded: Loaded
    reading: ImageCase | None
    fresh_reading: bool
    excerpts: list[Excerpt]
    figures: list[FigureExcerpt]


def lexical_query(question: str) -> str:
    """OR the question's terms so a natural-language question still matches.

    ``websearch_to_tsquery`` ANDs plain words; a full question rarely matches
    one chunk on every word. Stop words are dropped by the text search config.
    """
    terms = list(dict.fromkeys(t.lower() for t in TOKEN.findall(question)))[:40]
    return " or ".join(terms) if terms else question


async def load(session: AsyncSession, principal: Principal, body: AskRequest) -> Loaded:
    memory = MemoryState()
    if body.thread_id is not None:
        if await repo.get_thread(session, principal.user_id, body.thread_id) is None:
            raise HTTPException(status_code=404, detail="thread not found")
        memory = await repo.memory_state(session, body.thread_id)
    image = None
    if body.image_id is not None:
        image = await images.get_image(session, principal.user_id, body.image_id)
        if image is None:
            raise HTTPException(status_code=404, detail="image not found")
    label = ""
    if body.focus is not None:
        title = await search.source_title(session, principal.user_id, body.focus.source_id)
        if title is None:
            raise HTTPException(status_code=404, detail="source not found")
        label = f"{title}, page {body.focus.page_no}"
    return Loaded(memory, image, label)


def needs_reading(loaded: Loaded) -> bool:
    return loaded.image is not None and images.stored_reading(loaded.image["reading"]) is None


def read_attached(
    transport: Transport, store: ObjectStore, tenant_id: UUID, loaded: Loaded,
    report: Report | None = None,
) -> tuple[ImageCase | None, bool]:
    """(reading, fresh): the cached reading, or a new one from the vision agent."""
    if loaded.image is None:
        return None, False
    cached = images.stored_reading(loaded.image["reading"])
    if cached is not None:
        return cached, False
    if report is not None:
        report("reading_image")
    key = str(loaded.image["storage_key"])
    data = images.fetch_bytes(store, tenant_id, key)
    return read_image(transport, data, key.rsplit(".", 1)[-1]), True


def _boost(first: Sequence[dict[str, Any]], rest: Sequence[dict[str, Any]],
           limit: int) -> list[dict[str, Any]]:
    merged: dict[Any, dict[str, Any]] = {}
    for row in [*first, *rest]:
        merged.setdefault(row["id"], row)
    return list(merged.values())[:limit]


async def retrieve(
    session: AsyncSession, principal: Principal, body: AskRequest, loaded: Loaded,
    reading: tuple[ImageCase | None, bool],
) -> Prepared:
    """Hybrid search (Reader page first when focused); ends the transaction."""
    text_query = retrieval_text(body.question, reading[0])
    vector = await query_vector(principal.tenant_id, text_query)
    query = lexical_query(text_query)
    user = principal.user_id
    hits = await search.hybrid_search(session, user, query, vector, RETRIEVE)
    figures = await search.search_figures(session, user, query, FIGURE_CANDIDATES,
                                          query_vector=vector)
    if body.focus is not None:
        focus = body.focus
        hits = _boost(await search.page_chunks(session, user, focus.source_id, focus.page_no,
                                               FOCUS_CHUNKS), hits, RETRIEVE)
        figures = _boost(await search.page_figures(session, user, focus.source_id,
                                                   focus.page_no, FOCUS_FIGURES),
                         figures, FIGURE_CANDIDATES)
    await session.rollback()  # hold no transaction or connection during the model calls
    return Prepared(loaded, reading[0], reading[1], excerpts_from_hits(hits),
                    figures_from_hits(figures))


def _fold(transport: Transport, memory: MemoryState, report: Report | None) -> tuple[
        Sequence[Any], str, MemoryUpdate | None]:
    plan = plan_memory(memory)
    if not plan.fold:
        return plan.verbatim, plan.summary, None
    if report is not None:
        report("remembering")
    try:
        update = fold_memory(transport, plan)
    except ModelCallError as exc:  # keep the old summary; retry the fold next turn
        logger.warning("tutor_memory_failed", extra={"error_type": type(exc).__name__})
        return plan.verbatim, plan.summary, None
    return plan.verbatim, update.summary if update else plan.summary, update


def answer_work(
    transport: Transport, body: AskRequest, prepared: Prepared, drafts: bool = False,
    report: Report | None = None,
) -> tuple[GroundedAnswer, MemoryUpdate | None]:
    """Rolling memory, then the grounded, judged answer (drafts go to ``report``)."""
    history, summary, update = _fold(transport, prepared.loaded.memory, report)
    context = Context(summary=summary, image=prepared.reading,
                      reading=prepared.loaded.reading_label)
    answer = answer_question(
        transport, body.question, prepared.excerpts, list(history), body.allow_web,
        figures=prepared.figures, judge=get_settings().tutor_grounding_judge,
        on_status=report, context=context,
        on_draft=report if drafts and report is not None else None,
    )
    return answer, update


async def persist(
    session: AsyncSession, principal: Principal, body: AskRequest, prepared: Prepared,
    outcome: tuple[GroundedAnswer, MemoryUpdate | None],
) -> AskResponse:
    answer, memory = outcome
    await set_database_tenant(session, principal.tenant_id)
    thread_id = body.thread_id or await repo.create_thread(
        session, principal.tenant_id, principal.user_id, repo.thread_title(body.question))
    if prepared.fresh_reading and prepared.reading is not None and body.image_id is not None:
        await images.save_reading(session, body.image_id, prepared.reading,
                                  load_agent(IMAGE_AGENT).key)
    message_id = await repo.add_exchange(session, principal.tenant_id, thread_id,
                                         body.question, answer, body.image_id)
    if memory is not None:
        await repo.save_memory(session, thread_id, memory)
    await session.commit()
    _log(thread_id, message_id, answer, prepared, memory)
    return AskResponse(
        thread_id=thread_id, message_id=message_id, grounding=answer.grounding,
        segments=answer.segments, notice=answer.notice,
        dropped_segments=answer.dropped_segments, agent_version=answer.agent_version,
        excerpts_considered=len(prepared.excerpts), figures_considered=len(prepared.figures),
        judge=answer.judge, image_id=body.image_id, image_reading=prepared.reading,
    )


def _log(thread_id: UUID, message_id: UUID, answer: GroundedAnswer, prepared: Prepared,
         memory: MemoryUpdate | None) -> None:
    judge = answer.judge or JudgeStats(status="not_run")
    logger.info("tutor_answered", extra={
        "thread_id": str(thread_id), "message_id": str(message_id),
        "grounding": answer.grounding, "segments": len(answer.segments),
        "dropped_segments": answer.dropped_segments, "excerpts": len(prepared.excerpts),
        "figures": len(prepared.figures), "judge_status": judge.status,
        "judge_partial": judge.partial, "judge_unsupported": judge.unsupported,
        "image": prepared.reading is not None, "focus": bool(prepared.loaded.reading_label),
        "memory_folded": memory is not None,
    })
