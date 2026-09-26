"""SQL for the question bank and attempts.

Every statement runs in the caller's tenant session (RLS) and is additionally
scoped to the owning user, so a question is visible only to the person whose
sources it was generated from.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from packages.assessment.duplicates import normalize_stem
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, type, exam_tags, topic, stem, options, answer, explanation, citations, figure_id, "
    "status, quality, agent_version, created_at"
)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


async def insert_question(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, values: dict[str, Any]
) -> UUID:
    row = await session.execute(
        text(
            "INSERT INTO questions (tenant_id, user_id, type, exam_tags, topic, stem, options, "
            "answer, explanation, citations, figure_id, status, quality, agent_version, "
            "stem_norm, embedding, embed_model) VALUES "
            "(:t, :u, :type, CAST(:tags AS text[]), :topic, :stem, CAST(:options AS jsonb), "
            "CAST(:answer AS jsonb), :explanation, CAST(:citations AS jsonb), :figure, :status, "
            "CAST(:quality AS jsonb), :agent, :norm, CAST(:embedding AS vector), :embed_model) "
            "RETURNING id"
        ),
        {
            "t": tenant_id, "u": user_id, "type": values["type"], "tags": values["exam_tags"],
            "topic": values["topic"][:300], "stem": values["stem"],
            "options": dumps(values["options"]), "answer": dumps(values["answer"]),
            "explanation": values["explanation"], "citations": dumps(values["citations"]),
            "figure": values["figure_id"], "status": values["status"],
            "quality": dumps(values["quality"]), "agent": values["agent_version"],
            "norm": normalize_stem(values["stem"]), "embedding": values.get("embedding"),
            "embed_model": values.get("embed_model"),
        },
    )
    question_id: UUID = row.scalar_one()
    return question_id


async def get_question(
    session: AsyncSession, user_id: UUID, question_id: UUID
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM questions WHERE id = :q AND user_id = :u"),  # nosec B608 - constant column list; all values are bound parameters
            {"q": question_id, "u": user_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def get_questions(
    session: AsyncSession, user_id: UUID, ids: list[UUID]
) -> dict[str, dict[str, Any]]:
    rows = await session.execute(
        text(f"SELECT {_COLUMNS} FROM questions WHERE id = ANY(:ids) AND user_id = :u"),  # nosec B608 - constant column list; all values are bound parameters
        {"ids": ids, "u": user_id},
    )
    return {str(row["id"]): dict(row) for row in rows.mappings()}


def _where(user_id: UUID, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses = ["user_id = :u"]
    params: dict[str, Any] = {"u": user_id}
    for column in ("type", "status"):
        if filters.get(column):
            clauses.append(f"{column} = :{column}")
            params[column] = filters[column]
    if filters.get("exam_target"):
        clauses.append(":tag = ANY(exam_tags)")
        params["tag"] = filters["exam_target"]
    if filters.get("topic"):
        clauses.append("topic ILIKE :topic")
        params["topic"] = "%" + filters["topic"].replace("%", "").replace("_", " ") + "%"
    return " AND ".join(clauses), params


async def list_questions(
    session: AsyncSession, user_id: UUID, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    where, params = _where(user_id, filters)
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM questions WHERE {where} "  # nosec B608 - constant column list; all values are bound parameters
            "ORDER BY created_at DESC, id LIMIT :n OFFSET :o"
        ),
        {**params, "n": filters["limit"], "o": filters["offset"]},
    )
    return [dict(row) for row in rows.mappings()]


async def pick_exam_questions(
    session: AsyncSession, user_id: UUID, filters: dict[str, Any], count: int
) -> list[tuple[UUID, str]]:
    """Random active items of the requested types matching the filters: (id, type)."""
    where, params = _where(user_id, {"status": "active", "exam_target": filters.get("exam_target"),
                                     "topic": filters.get("topic")})
    rows = await session.execute(
        text(
            f"SELECT id, type FROM questions WHERE {where} AND type = ANY(:types) "  # nosec B608 - constant column list; all values are bound parameters
            "ORDER BY random() LIMIT :n"
        ),
        {**params, "types": list(filters.get("types") or ["sba"]), "n": count},
    )
    return [(row[0], row[1]) for row in rows]


async def in_open_exam(session: AsyncSession, user_id: UUID, question_id: UUID) -> bool:
    """True while the question sits in one of the user's unsubmitted, unexpired exams."""
    row = await session.execute(
        text(
            "SELECT 1 FROM exams WHERE user_id = :u AND submitted_at IS NULL "
            "AND question_ids @> ARRAY[CAST(:q AS uuid)] "
            "AND (deadline_at IS NULL OR deadline_at > now()) LIMIT 1"
        ),
        {"u": user_id, "q": question_id},
    )
    return row.first() is not None


async def insert_attempt(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, values: dict[str, Any]
) -> UUID | None:
    """Insert an attempt; returns None when an exam attempt for the item already exists."""
    row = await session.execute(
        text(
            "INSERT INTO attempts (tenant_id, user_id, question_id, exam_id, response, score, "
            "max_score, feedback, graded_by) VALUES (:t, :u, :q, :e, CAST(:response AS jsonb), "
            ":score, :max, CAST(:feedback AS jsonb), :by) "
            "ON CONFLICT (tenant_id, exam_id, question_id) WHERE exam_id IS NOT NULL "
            "DO NOTHING RETURNING id"
        ),
        {
            "t": tenant_id, "u": user_id, "q": values["question_id"],
            "e": values.get("exam_id"), "response": dumps(values["response"]),
            "score": values["score"], "max": values["max_score"],
            "feedback": dumps(values["feedback"]), "by": values["graded_by"],
        },
    )
    attempt_id: UUID | None = row.scalar_one_or_none()
    return attempt_id
