"""Past-paper mode: count question topics per page, then suggest topic weights.

Each page is a resumable unit (``knowledge_runs``). Its topic counts replace any
earlier counts for that page, so a re-run never double-counts. After all pages,
weights are recomputed from every past paper the user has analysed and stored
unapproved; a weight whose value changes loses its earlier approval.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from apps.worker.app.ingest.db import as_json, tenant_tx
from apps.worker.app.knowledge import db
from apps.worker.app.knowledge.runtime import KnowledgeDeps, call_agent
from packages.knowledge.curriculum import mapping_status, prompt_listing, system_codes
from packages.knowledge.models import PaperTopics
from packages.knowledge.text import collapse_ws, word_count
from packages.knowledge.weights import Observation, Weight, compute_weights
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AGENT = "paper_topics/v1"
THIN_TEXT_WORDS = 20


def _prompt(source: dict[str, Any], page: dict[str, Any], with_image: bool) -> str:
    image = "The rendered page image is attached; read it.\n" if with_image else ""
    return (
        f"Allowed curriculum codes:\n{prompt_listing()}\n\nSource title: {source['title']}\n"
        f"Page: {page['page_no']}\n{image}\nPage text:\n{page['text'][:12000]}"
    )


async def run_papers(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], version: int,
    exam_target: str | None, year: int | None,
) -> str:
    async with tenant_tx(deps.engine, tenant_id) as session:
        pages = await db.page_texts(session, source["id"])
    questions = 0
    for page in pages:
        questions += await _page(deps, tenant_id, source, page, version, exam_target, year)
    async with tenant_tx(deps.engine, tenant_id) as session:
        weights = await recompute_weights(session, tenant_id, source["uploaded_by"])
    return f"pages:{len(pages)},questions:{questions},weights:{weights}"


async def _page(
    deps: KnowledgeDeps, tenant_id: UUID, source: dict[str, Any], page: dict[str, Any],
    version: int, exam_target: str | None, year: int | None,
) -> int:
    unit = f"page:{page['page_no']}:{db.unit_hash(page['text'])}"
    async with tenant_tx(deps.engine, tenant_id) as session:
        if await db.run_done(session, source["id"], unit, AGENT, version):
            return 0
    files: list[tuple[str, bytes]] = []
    if word_count(page["text"]) < THIN_TEXT_WORDS and page["image_key"] and deps.store:
        files = [(f"page-{page['page_no']:05d}.png", deps.store.get(page["image_key"]))]
    if not files and not page["text"].strip():
        return 0
    result = call_agent(deps, "paper_topics", _prompt(source, page, bool(files)), files)
    async with tenant_tx(deps.engine, tenant_id) as session:
        if not isinstance(result, PaperTopics):
            await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                                "failed", "model_error")
            return 0
        counted = await _store_counts(session, tenant_id, source, page, result,
                                      exam_target, year)
        await db.record_run(session, tenant_id, source["id"], unit, AGENT, version,
                            "succeeded", f"questions:{counted}")
    return counted


def page_counts(result: PaperTopics) -> Counter[tuple[str, str]]:
    """(curriculum_code, topic) -> questions on the page; unknown codes dropped."""
    counts: Counter[tuple[str, str]] = Counter()
    if not result.is_exam_paper:
        return counts
    for question in result.questions:
        if mapping_status(question.curriculum_code, question.confidence) is None:
            continue
        topic = collapse_ws(question.topic).lower()[:200]
        counts[(question.curriculum_code, topic)] += 1
    return counts


async def _store_counts(
    session: AsyncSession, tenant_id: UUID, source: dict[str, Any], page: dict[str, Any],
    result: PaperTopics, exam_target: str | None, year: int | None,
) -> int:
    await session.execute(
        text("DELETE FROM topic_frequencies WHERE source_id = :s AND page_no = :p"),
        {"s": source["id"], "p": page["page_no"]},
    )
    counts = page_counts(result)
    for (code, topic), count in counts.items():
        await session.execute(
            text(
                """
                INSERT INTO topic_frequencies (tenant_id, user_id, source_id, page_no,
                    exam_target, paper_label, year, curriculum_code, topic, count, agent_version)
                VALUES (:t, :u, :s, :p, :target, :label, :year, :code, :topic, :n, :agent)
                """
            ),
            {"t": tenant_id, "u": source["uploaded_by"], "s": source["id"],
             "p": page["page_no"], "target": exam_target or result.exam_target,
             "label": (result.paper_label or source["title"])[:200],
             "year": result.year or year, "code": code, "topic": topic, "n": count,
             "agent": AGENT},
        )
    return sum(counts.values())


async def recompute_weights(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> int:
    rows = await session.execute(
        text(
            "SELECT exam_target, curriculum_code, topic, source_id, paper_label, year, count "
            "FROM topic_frequencies WHERE user_id = :u"
        ),
        {"u": user_id},
    )
    observations = [
        Observation(r["exam_target"], r["curriculum_code"], r["topic"],
                    f"{r['source_id']}:{r['paper_label']}:{r['year']}", r["year"], r["count"])
        for r in rows.mappings()
    ]
    weights = compute_weights(observations, system_codes())
    for weight in weights:
        await _upsert_weight(session, tenant_id, user_id, weight)
    await session.execute(  # topics no longer observed; now() is the transaction time
        text("DELETE FROM topic_weights WHERE user_id = :u AND computed_at < now()"),
        {"u": user_id},
    )
    return len(weights)


async def _upsert_weight(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, weight: Weight
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO topic_weights (tenant_id, user_id, exam_target, curriculum_code, topic,
                                       weight, basis)
            VALUES (:t, :u, :target, :code, :topic, :w, CAST(:basis AS jsonb))
            ON CONFLICT (tenant_id, user_id, exam_target, curriculum_code, topic) DO UPDATE SET
                basis = EXCLUDED.basis, computed_at = now(),
                approved = topic_weights.approved AND topic_weights.weight = EXCLUDED.weight,
                approved_at = CASE WHEN topic_weights.weight = EXCLUDED.weight
                                   THEN topic_weights.approved_at END,
                approved_by = CASE WHEN topic_weights.weight = EXCLUDED.weight
                                   THEN topic_weights.approved_by END,
                weight = EXCLUDED.weight
            """
        ),
        {"t": tenant_id, "u": user_id, "target": weight.exam_target,
         "code": weight.curriculum_code, "topic": weight.topic, "w": weight.weight,
         "basis": as_json(weight.basis)},
    )
