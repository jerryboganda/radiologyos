"""SQL for the planner's real signals, the baseline diagnostic, and weekly reports.

Mixed into ``SqlStudyRepo``: every statement runs in the caller's tenant session
(RLS) and is additionally scoped to the calling user. A question's curriculum
system is resolved from the chunks it cites: accepted curriculum mappings and
the user's cards on those chunks vote, the most common code wins (ties by code).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from apps.api.app.assessment import exams
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
QUESTION_SYSTEMS = f"""
WITH cited AS (
    SELECT q.id AS question_id,
           CASE WHEN c->>'chunk_id' ~ '{_UUID_RE}' THEN CAST(c->>'chunk_id' AS uuid) END
               AS chunk_id
    FROM questions q CROSS JOIN LATERAL jsonb_array_elements(q.citations) AS c
    WHERE q.user_id = :u AND c->>'kind' = 'chunk'
), votes AS (
    SELECT cited.question_id, m.curriculum_code FROM cited
    JOIN curriculum_mappings m ON m.chunk_id = cited.chunk_id AND m.status = 'accepted'
    UNION ALL
    SELECT cited.question_id, k.curriculum_code FROM cited
    JOIN cards k ON k.source_chunk_id = cited.chunk_id AND k.user_id = :u
), qsys AS (
    SELECT DISTINCT ON (question_id) question_id, curriculum_code
    FROM votes GROUP BY question_id, curriculum_code
    ORDER BY question_id, count(*) DESC, curriculum_code
)
"""  # nosec B608 - interpolates only the constant _UUID_RE; values are bound
BASELINE_COLUMNS = (
    "b.id, b.exam_id, b.question_ids, b.systems, b.started_at, b.submitted_at, b.results, "
    "e.deadline_at"
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class StudyDepthSql:
    session: AsyncSession
    tenant_id: UUID

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self.session.execute(text(sql), params)
        return [dict(row) for row in result.mappings()]

    async def _row(self, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        row = (await self.session.execute(text(sql), params)).mappings().first()
        return dict(row) if row else None

    async def approved_weights(self, user_id: UUID) -> list[dict[str, Any]]:
        rows = await self._rows(
            "SELECT exam_target, curriculum_code, weight FROM topic_weights "
            "WHERE user_id = :u AND approved AND topic = ''", {"u": user_id})
        return [{**row, "weight": float(row["weight"])} for row in rows]

    async def question_attempts(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        rows = await self._rows(
            QUESTION_SYSTEMS + """
            SELECT qsys.curriculum_code, a.question_id, a.score, a.max_score, a.created_at
            FROM attempts a JOIN qsys ON qsys.question_id = a.question_id
            WHERE a.user_id = :u AND a.created_at >= :since
            """, {"u": user_id, "since": since})  # nosec B608 - constant SQL; bound values
        return [{**r, "score": float(r["score"]), "max_score": float(r["max_score"])}
                for r in rows]

    async def question_counts(self, user_id: UUID) -> list[dict[str, Any]]:
        return await self._rows(
            QUESTION_SYSTEMS + """
            SELECT qsys.curriculum_code, count(*) AS questions,
                   count(done.question_id) AS attempted
            FROM qsys JOIN questions q ON q.id = qsys.question_id AND q.status = 'active'
            LEFT JOIN (SELECT DISTINCT question_id FROM attempts WHERE user_id = :u) AS done
                ON done.question_id = q.id
            GROUP BY qsys.curriculum_code
            """, {"u": user_id})  # nosec B608 - constant SQL; bound values

    async def baseline_candidates(self, user_id: UUID) -> list[dict[str, Any]]:
        return await self._rows(
            QUESTION_SYSTEMS + """
            SELECT q.id AS question_id, qsys.curriculum_code
            FROM questions q JOIN qsys ON qsys.question_id = q.id
            WHERE q.user_id = :u AND q.type = 'sba' AND q.status = 'active'
            """, {"u": user_id})  # nosec B608 - constant SQL; bound values

    async def latest_baseline(self, user_id: UUID) -> dict[str, Any] | None:
        return await self._row(
            f"SELECT {BASELINE_COLUMNS} FROM baseline_tests b "  # nosec B608 - constant columns
            "JOIN exams e ON e.id = b.exam_id AND e.tenant_id = b.tenant_id "
            "WHERE b.user_id = :u ORDER BY b.created_at DESC, b.id LIMIT 1", {"u": user_id})

    async def create_baseline(
        self, user_id: UUID, systems: dict[str, str], minutes: int, now: datetime
    ) -> dict[str, Any]:
        ids = [UUID(q) for q in systems]
        config = {"kind": "baseline", "mode": "exam", "count": len(ids),
                  "time_limit_minutes": minutes, "available": len(ids)}
        exam = await self._row(
            "INSERT INTO exams (tenant_id, user_id, mode, config, question_ids, started_at, "
            "deadline_at) VALUES (:t, :u, 'exam', CAST(:config AS jsonb), "
            "CAST(:ids AS uuid[]), :now, :deadline) RETURNING id, deadline_at",
            {"t": self.tenant_id, "u": user_id, "config": _dumps(config), "ids": ids,
             "now": now, "deadline": now + timedelta(minutes=minutes)})
        assert exam is not None
        row = await self._row(
            "INSERT INTO baseline_tests (tenant_id, user_id, exam_id, question_ids, systems, "
            "started_at) VALUES (:t, :u, :e, CAST(:ids AS uuid[]), CAST(:systems AS jsonb), "
            ":now) RETURNING id, exam_id, question_ids, systems, started_at, submitted_at, "
            "results",
            {"t": self.tenant_id, "u": user_id, "e": exam["id"], "ids": ids,
             "systems": _dumps(systems), "now": now})
        assert row is not None
        return {**row, "deadline_at": exam["deadline_at"]}

    async def baseline_exam(self, user_id: UUID, exam_id: UUID) -> dict[str, Any] | None:
        """The linked exam, graded first if its deadline has passed."""
        return await exams.read_exam(self.session, self.tenant_id, user_id, exam_id)

    async def finish_baseline(
        self, user_id: UUID, baseline_id: UUID, submitted_at: datetime,
        results: Sequence[dict[str, Any]],
    ) -> None:
        await self.session.execute(
            text("UPDATE baseline_tests SET submitted_at = :s, results = CAST(:r AS jsonb) "
                 "WHERE id = :b AND user_id = :u AND submitted_at IS NULL"),
            {"s": submitted_at, "r": _dumps(list(results)), "b": baseline_id, "u": user_id})

    async def reviews_between(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        return await self._rows(
            "SELECT reviewed_at, rating, state_before FROM card_reviews WHERE user_id = :u "
            "AND reviewed_at >= :a AND reviewed_at < :b", {"u": user_id, "a": start, "b": end})

    async def attempts_between(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        rows = await self._rows(
            "SELECT created_at, score, max_score FROM attempts WHERE user_id = :u "
            "AND created_at >= :a AND created_at < :b", {"u": user_id, "a": start, "b": end})
        return [{**r, "score": float(r["score"]), "max_score": float(r["max_score"])}
                for r in rows]

    async def save_report(
        self, user_id: UUID, week_start: date, version: int, report: dict[str, Any]
    ) -> datetime:
        row = await self._row(
            """
            INSERT INTO weekly_reports (tenant_id, user_id, week_start, report_version, report)
            VALUES (:t, :u, :w, :v, CAST(:r AS jsonb))
            ON CONFLICT (tenant_id, user_id, week_start) DO UPDATE SET
                report_version = EXCLUDED.report_version, report = EXCLUDED.report,
                generated_at = now()
            RETURNING generated_at
            """,
            {"t": self.tenant_id, "u": user_id, "w": week_start, "v": version,
             "r": _dumps(report)})
        assert row is not None
        generated: datetime = row["generated_at"]
        return generated

    async def latest_report(self, user_id: UUID) -> dict[str, Any] | None:
        return await self._row(
            "SELECT week_start, report_version, report, generated_at FROM weekly_reports "
            "WHERE user_id = :u ORDER BY week_start DESC LIMIT 1", {"u": user_id})
