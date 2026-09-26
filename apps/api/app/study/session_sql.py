"""SQL for Today sessions: durable steps, learn material, SBA and viva items.

Mixed into ``SqlStudyRepo``. Every statement runs in the caller's tenant session
(RLS) and is also scoped to the calling user. Session rows hold ids, statuses and
the user's own answers only; source text is read live from the library, so a
deleted source simply disappears from an old session.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from apps.api.app.assessment import exams, store
from apps.api.app.assessment.question_systems import QUESTION_SYSTEMS
from apps.api.app.core.time import now_utc
from apps.api.app.study import weakness_sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SESSION_COLUMNS = (
    "id, session_date, session_version, plan_version, status, summary, created_at, "
    "completed_at"
)
STEP_COLUMNS = (
    "step_no, kind, status, minutes, payload, result, started_at, deadline_at, completed_at"
)
STEP_FIELDS = ("status", "started_at", "deadline_at", "completed_at")
OPEN_EXAM = """
    NOT EXISTS (SELECT 1 FROM exams e WHERE e.user_id = :u AND e.submitted_at IS NULL
        AND e.question_ids @> ARRAY[q.id]
        AND (e.deadline_at IS NULL OR e.deadline_at > now()))
"""
CANDIDATES = QUESTION_SYSTEMS + f"""
SELECT q.id AS question_id, q.type, qsys.curriculum_code,
       (SELECT max(a.created_at) FROM attempts a
        WHERE a.question_id = q.id AND a.user_id = :u) AS last_attempt_at
FROM questions q LEFT JOIN qsys ON qsys.question_id = q.id
WHERE q.user_id = :u AND q.status = 'active' AND q.type = ANY(CAST(:types AS text[]))
  AND {OPEN_EXAM}
ORDER BY q.created_at, q.id
"""  # nosec B608 - constant SQL fragments; all values are bound
LEARN = """
WITH picked AS (
    SELECT m.chunk_id, max(m.confidence)::float AS score FROM curriculum_mappings m
    WHERE m.status = 'accepted' AND m.chunk_id IS NOT NULL
      AND m.curriculum_code = ANY(CAST(:codes AS text[]))
    GROUP BY m.chunk_id
    UNION ALL
    SELECT k.source_chunk_id, 0.5 FROM cards k
    WHERE k.user_id = :u AND k.source_chunk_id IS NOT NULL
      AND k.curriculum_code = ANY(CAST(:codes AS text[]))
)
SELECT c.id, c.source_id, c.page_from, c.page_to, max(p.score) AS score, c.chunk_no
FROM picked p JOIN chunks c ON c.id = p.chunk_id
JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
WHERE s.uploaded_by = :u AND s.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM study_session_steps st WHERE st.user_id = :u
      AND st.kind = 'learn' AND st.status = 'done'
      AND st.payload->'chunk_ids' @> jsonb_build_array(c.id::text))
GROUP BY c.id, c.source_id, c.page_from, c.page_to, c.chunk_no
ORDER BY score DESC, c.source_id, c.chunk_no
LIMIT :n
"""
NEAR_FIGURES = """
SELECT DISTINCT f.id, f.source_id, f.page_no, f.figure_no
FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id
JOIN unnest(CAST(:srcs AS uuid[]), CAST(:froms AS int[]), CAST(:tos AS int[]))
    AS r(source_id, page_from, page_to)
    ON f.source_id = r.source_id AND f.page_no BETWEEN r.page_from AND r.page_to
WHERE s.uploaded_by = :u AND s.deleted_at IS NULL AND (f.description <> '' OR f.caption <> '')
ORDER BY f.source_id, f.page_no, f.figure_no
LIMIT :n
"""
FIGURES = """
SELECT f.id, f.source_id, s.title AS source_title, f.page_no, f.caption, f.description,
       f.modality, f.image_key IS NOT NULL AS has_image
FROM figures f JOIN sources s ON s.id = f.source_id AND s.tenant_id = f.tenant_id
WHERE s.uploaded_by = :u AND s.deleted_at IS NULL AND f.id = ANY(CAST(:ids AS uuid[]))
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class SessionSql:
    session: AsyncSession
    tenant_id: UUID

    async def _fetch(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(r) for r in (await self.session.execute(text(sql), params)).mappings()]

    async def _with_steps(self, row: dict[str, Any] | None,
                          user_id: UUID) -> dict[str, Any] | None:
        if row is None:
            return None
        row["steps"] = await self._fetch(
            f"SELECT {STEP_COLUMNS} FROM study_session_steps "  # nosec B608 - constant columns
            "WHERE session_id = :s AND user_id = :u ORDER BY step_no",
            {"s": row["id"], "u": user_id})
        return row

    async def get_session(self, user_id: UUID, day: date) -> dict[str, Any] | None:
        rows = await self._fetch(
            f"SELECT {SESSION_COLUMNS} FROM study_sessions "  # nosec B608 - constant columns
            "WHERE user_id = :u AND session_date = :d", {"u": user_id, "d": day})
        return await self._with_steps(rows[0] if rows else None, user_id)

    async def get_session_by_id(self, user_id: UUID, session_id: UUID) -> dict[str, Any] | None:
        rows = await self._fetch(
            f"SELECT {SESSION_COLUMNS} FROM study_sessions "  # nosec B608 - constant columns
            "WHERE user_id = :u AND id = :s", {"u": user_id, "s": session_id})
        return await self._with_steps(rows[0] if rows else None, user_id)

    async def create_session(
        self, user_id: UUID, day: date, versions: tuple[int, int],
        steps: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Insert the day's session once; a concurrent or repeated build keeps the first."""
        created = await self._fetch(
            "INSERT INTO study_sessions (tenant_id, user_id, session_date, session_version, "
            "plan_version) VALUES (:t, :u, :d, :sv, :pv) "
            "ON CONFLICT (tenant_id, user_id, session_date) DO NOTHING RETURNING id",
            {"t": self.tenant_id, "u": user_id, "d": day, "sv": versions[0], "pv": versions[1]})
        if created:
            for step in steps:
                await self.session.execute(text(
                    "INSERT INTO study_session_steps (tenant_id, session_id, user_id, step_no, "
                    "kind, minutes, payload) VALUES (:t, :s, :u, :n, :k, :m, "
                    "CAST(:p AS jsonb))"),
                    {"t": self.tenant_id, "s": created[0]["id"], "u": user_id,
                     "n": step["step_no"], "k": step["kind"], "m": step["minutes"],
                     "p": _dumps(step["payload"])})
        found = await self.get_session(user_id, day)
        assert found is not None
        return found

    async def update_step(self, user_id: UUID, session_id: UUID, step_no: int,
                          changes: Mapping[str, Any]) -> None:
        fields = [f for f in STEP_FIELDS if f in changes]
        sets = [f"{f} = :{f}" for f in fields]
        params: dict[str, Any] = {f: changes[f] for f in fields}
        if "result" in changes:
            sets.append("result = CAST(:result AS jsonb)")
            params["result"] = _dumps(changes["result"])
        if not sets:
            return
        await self.session.execute(text(
            f"UPDATE study_session_steps SET {', '.join(sets)} "  # nosec B608 - whitelisted columns
            "WHERE session_id = :s AND user_id = :u AND step_no = :n"),
            {**params, "s": session_id, "u": user_id, "n": step_no})

    async def finish_session(self, user_id: UUID, session_id: UUID,
                             summary: Mapping[str, Any], now: datetime) -> None:
        await self.session.execute(text(
            "UPDATE study_sessions SET status = 'completed', completed_at = :now, "
            "summary = CAST(:summary AS jsonb) WHERE id = :s AND user_id = :u "
            "AND status = 'active'"),
            {"now": now, "summary": _dumps(summary), "s": session_id, "u": user_id})

    async def completed_sessions(self, user_id: UUID, since: date) -> list[dict[str, Any]]:
        return await self._fetch(
            "SELECT session_date, summary FROM study_sessions WHERE user_id = :u "
            "AND status = 'completed' AND session_date >= :d ORDER BY session_date",
            {"u": user_id, "d": since})

    async def cards_by_ids(self, user_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
        from apps.api.app.study.repo import CARD_COLUMNS

        return await self._fetch(
            f"SELECT {CARD_COLUMNS} FROM cards WHERE user_id = :u "  # nosec B608 - constant columns
            "AND id = ANY(CAST(:ids AS uuid[])) ORDER BY due_at, id",
            {"u": user_id, "ids": list(ids)})

    async def figures_by_ids(self, user_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
        return await self._fetch(FIGURES, {"u": user_id, "ids": list(ids)})

    async def learn_material(
        self, user_id: UUID, codes: Sequence[str], limit: int, figures: int
    ) -> tuple[list[str], list[str]]:
        chunks = await self._fetch(LEARN, {"u": user_id, "codes": list(codes), "n": limit})
        if not chunks:
            return [], []
        near = await self._fetch(NEAR_FIGURES, {
            "u": user_id, "n": figures, "srcs": [c["source_id"] for c in chunks],
            "froms": [c["page_from"] for c in chunks], "tos": [c["page_to"] for c in chunks]})
        return [str(c["id"]) for c in chunks], [str(f["id"]) for f in near]

    async def question_candidates(
        self, user_id: UUID, types: Sequence[str]
    ) -> list[dict[str, Any]]:
        return await self._fetch(CANDIDATES, {"u": user_id, "types": list(types)})

    async def open_retests(self, user_id: UUID, limit: int) -> list[dict[str, Any]]:
        return await weakness_sql.open_retests(self.session, user_id, limit)

    async def questions_by_ids(
        self, user_id: UUID, ids: Sequence[UUID]
    ) -> dict[str, dict[str, Any]]:
        return await store.get_questions(self.session, user_id, list(ids))

    async def question_locked(self, user_id: UUID, question_id: UUID) -> bool:
        return await store.in_open_exam(self.session, user_id, question_id)

    async def record_sba(
        self, user_id: UUID, question: Mapping[str, Any], graded: Mapping[str, Any],
        confidence: int | None, session_id: UUID, now: datetime,
    ) -> UUID | None:
        attempt_id = await store.insert_attempt(self.session, self.tenant_id, user_id, {
            "question_id": question["id"], "confidence": confidence,
            "response": {"selected_option": graded["selected_option"],
                         "session_id": str(session_id)},
            "score": graded["score"], "max_score": graded["max_score"],
            "feedback": {"correct": graded["correct"]}, "graded_by": exams.SBA_GRADER})
        await weakness_sql.after_sba(self.session, self.tenant_id, user_id, question,
                                     attempt_id, bool(graded["correct"]), "sba_wrong", now)
        return attempt_id

    async def record_lapse(self, user_id: UUID, card: Mapping[str, Any], review_id: UUID,
                           now: datetime) -> None:
        await weakness_sql.record_lapse(self.session, self.tenant_id, user_id, card,
                                        review_id, now)

    async def submit_viva(self, user_id: UUID, question: Mapping[str, Any],
                          answer: str) -> dict[str, Any] | None:
        """A one-item practice exam: the existing async ``seq_grade`` path grades it."""
        qid = str(question["id"])
        config = {"kind": "session_viva", "mode": "practice", "count": 1, "available": 1,
                  "types": [question["type"]], "free_text_ids": [qid]}
        created = await self._fetch(
            "INSERT INTO exams (tenant_id, user_id, mode, config, question_ids, started_at) "
            "VALUES (:t, :u, 'practice', CAST(:c AS jsonb), CAST(:ids AS uuid[]), :now) "
            "RETURNING id",
            {"t": self.tenant_id, "u": user_id, "c": _dumps(config), "ids": [question["id"]],
             "now": now_utc()})
        exam_id = created[0]["id"]
        await exams.save_answers(self.session, user_id, exam_id, 0, {}, {qid: answer})
        return await exams.submit(self.session, self.tenant_id, user_id, exam_id)

    async def viva_exam(self, user_id: UUID, exam_id: UUID) -> dict[str, Any] | None:
        return await exams.load_exam(self.session, user_id, exam_id)
