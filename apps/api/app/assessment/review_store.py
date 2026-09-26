"""SQL for the owner's draft review queue (list, citation validity, update)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.assessment import store
from packages.assessment.duplicates import normalize_stem
from packages.assessment.review import cited_targets
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, type, exam_tags, topic, stem, options, answer, explanation, citations, figure_id, "
    "status, status_reason, quality, agent_version, created_at"
)


async def list_drafts(
    session: AsyncSession, user_id: UUID, limit: int, offset: int
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM questions WHERE user_id = :u AND status = 'draft' "  # nosec B608 - constant column list; values are bound
            "ORDER BY created_at DESC, id LIMIT :n OFFSET :o"
        ),
        {"u": user_id, "n": limit, "o": offset},
    )
    return [dict(row) for row in rows.mappings()]


async def get_for_review(
    session: AsyncSession, user_id: UUID, question_id: UUID
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM questions WHERE id = :q AND user_id = :u FOR UPDATE"),  # nosec B608 - constant column list; values are bound
            {"q": question_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def citations_valid(
    session: AsyncSession, user_id: UUID, question: dict[str, Any]
) -> bool:
    """Every cited source page and figure still exists in the owner's live library."""
    pages, figures = cited_targets(question)
    if not pages and not figures:
        return False
    for source_id, page_no in pages:
        found = await session.execute(
            text(
                "SELECT 1 FROM source_pages p JOIN sources s "
                "ON s.id = p.source_id AND s.tenant_id = p.tenant_id "
                "WHERE p.source_id = :s AND p.page_no = :p AND s.uploaded_by = :u "
                "AND s.deleted_at IS NULL"
            ),
            {"s": source_id, "p": page_no, "u": user_id},
        )
        if found.first() is None:
            return False
    if figures:
        found_figures = await session.execute(
            text(
                "SELECT count(*) FROM figures f JOIN sources s "
                "ON s.id = f.source_id AND s.tenant_id = f.tenant_id "
                "WHERE f.id = ANY(:ids) AND s.uploaded_by = :u AND s.deleted_at IS NULL"
            ),
            {"ids": list(figures), "u": user_id},
        )
        if int(found_figures.scalar_one()) != len(figures):
            return False
    return True


async def save_review(
    session: AsyncSession, user_id: UUID, question: dict[str, Any], reason: str | None
) -> None:
    """Persist wording, status, and quality for a reviewed question."""
    await session.execute(
        text(
            "UPDATE questions SET stem = :stem, topic = :topic, explanation = :explanation, "
            "options = CAST(:options AS jsonb), answer = CAST(:answer AS jsonb), "
            "quality = CAST(:quality AS jsonb), stem_norm = :norm, "
            "status_changed_at = CASE WHEN status <> :status THEN now() "
            "ELSE status_changed_at END, status = :status, status_reason = :reason "
            "WHERE id = :q AND user_id = :u"
        ),
        {"stem": question["stem"], "topic": question["topic"][:300],
         "explanation": question["explanation"], "options": store.dumps(question["options"]),
         "answer": store.dumps(question["answer"]), "quality": store.dumps(question["quality"]),
         "norm": normalize_stem(question["stem"]), "status": question["status"],
         "reason": reason, "q": question["id"], "u": user_id},
    )
