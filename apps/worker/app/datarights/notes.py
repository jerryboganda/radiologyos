"""Readable Markdown of a user's cards and claims, each with its citation.

Part of the account export (ADR 0018). Every entry keeps the source title and
page range so the notes stay provenance-first outside the app.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _pages(page_from: Any, page_to: Any) -> str:
    if page_from is None:
        return "page unknown"
    return f"p. {page_from}" if page_from == page_to else f"pp. {page_from}-{page_to}"


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cite(title: Any, page_from: Any, page_to: Any) -> str:
    return f"Source: {_one_line(title) or 'deleted source'}, {_pages(page_from, page_to)}"


async def cards_markdown(session: AsyncSession, user_id: UUID) -> str:
    rows = await session.execute(
        text(
            """
            SELECT c.curriculum_code, c.topic, c.front, c.back, s.title,
                   c.citation->>'page_from' AS page_from, c.citation->>'page_to' AS page_to
            FROM cards c LEFT JOIN sources s ON s.id = c.source_id
            WHERE c.user_id = :u
            ORDER BY c.curriculum_code, c.topic, c.created_at
            """
        ),
        {"u": user_id},
    )
    lines = ["# Cards", ""]
    for row in rows.mappings():
        lines += [
            f"## {_one_line(row['topic'])} ({row['curriculum_code']})", "",
            f"**Q:** {row['front'].strip()}", "",
            f"**A:** {row['back'].strip()}", "",
            f"_{_cite(row['title'], row['page_from'], row['page_to'])}_", "",
        ]
    return "\n".join(lines)


async def claims_markdown(session: AsyncSession, user_id: UUID) -> str:
    rows = await session.execute(
        text(
            """
            SELECT k.name, c.statement, c.evidence_span, c.status, c.page_from, c.page_to,
                   s.title
            FROM claims c
            JOIN concepts k ON k.id = c.concept_id
            JOIN sources s ON s.id = c.source_id
            WHERE s.uploaded_by = :u
            ORDER BY k.name, c.importance DESC, c.created_at
            """
        ),
        {"u": user_id},
    )
    lines = ["# Claims", ""]
    concept = None
    for row in rows.mappings():
        if row["name"] != concept:
            concept = row["name"]
            lines += [f"## {_one_line(concept)}", ""]
        status = "" if row["status"] == "active" else f" ({row['status']})"
        lines += [
            f"- {_one_line(row['statement'])}{status}",
            f"  - Evidence: \"{_one_line(row['evidence_span'])}\"",
            f"  - {_cite(row['title'], row['page_from'], row['page_to'])}",
        ]
    return "\n".join(lines) + "\n"
