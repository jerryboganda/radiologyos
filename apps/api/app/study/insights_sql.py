"""SQL for the progress insights: per-curriculum-code coverage and rated SBA answers.

Mixed into ``SqlStudyRepo``; tenant session (RLS) plus a per-user filter. A
passage (chunk) counts toward a code when an accepted curriculum mapping puts
it there; it counts as studied when the user reviewed a card made from it,
attempted a question citing it, or finished a Today learn step that showed it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
COVERAGE = f"""
WITH mapped AS (
    SELECT DISTINCT m.curriculum_code, m.chunk_id
    FROM curriculum_mappings m
    JOIN sources s ON s.id = m.source_id AND s.tenant_id = m.tenant_id
    WHERE m.status = 'accepted' AND m.chunk_id IS NOT NULL
      AND s.uploaded_by = :u AND s.deleted_at IS NULL
), cited AS (
    SELECT q.id AS question_id, CAST(c->>'chunk_id' AS uuid) AS chunk_id
    FROM questions q CROSS JOIN LATERAL jsonb_array_elements(q.citations) AS c
    WHERE q.user_id = :u AND c->>'kind' = 'chunk' AND c->>'chunk_id' ~ '{_UUID_RE}'
), touched AS (
    SELECT source_chunk_id AS chunk_id FROM cards
    WHERE user_id = :u AND last_review_at IS NOT NULL AND source_chunk_id IS NOT NULL
    UNION
    SELECT cited.chunk_id FROM cited
    JOIN attempts a ON a.question_id = cited.question_id AND a.user_id = :u
    UNION
    SELECT CAST(x AS uuid) FROM study_session_steps st
    CROSS JOIN LATERAL jsonb_array_elements_text(st.payload->'chunk_ids') AS x
    WHERE st.user_id = :u AND st.kind = 'learn' AND st.status = 'done'
      AND x ~ '{_UUID_RE}'
), scored AS (
    SELECT DISTINCT mapped.curriculum_code, a.id, a.score, a.max_score
    FROM mapped JOIN cited ON cited.chunk_id = mapped.chunk_id
    JOIN attempts a ON a.question_id = cited.question_id AND a.user_id = :u
    WHERE a.created_at >= :since
), totals AS (
    SELECT curriculum_code, sum(score)::float AS score, sum(max_score)::float AS max_score
    FROM scored GROUP BY curriculum_code
)
SELECT mapped.curriculum_code, count(*) AS material, count(touched.chunk_id) AS studied,
       coalesce(max(totals.score), 0) AS score, coalesce(max(totals.max_score), 0) AS max_score
FROM mapped
LEFT JOIN touched ON touched.chunk_id = mapped.chunk_id
LEFT JOIN totals ON totals.curriculum_code = mapped.curriculum_code
GROUP BY mapped.curriculum_code
"""  # nosec B608 - interpolates only the constant _UUID_RE; values are bound


class InsightsSql:
    session: AsyncSession
    tenant_id: UUID

    async def coverage_stats(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        rows = await self.session.execute(text(COVERAGE), {"u": user_id, "since": since})
        return [{**dict(r), "score": float(r["score"]), "max_score": float(r["max_score"])}
                for r in rows.mappings()]

    async def rated_attempts(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        rows = await self.session.execute(text(
            "SELECT confidence, score, max_score FROM attempts WHERE user_id = :u "
            "AND confidence IS NOT NULL AND created_at >= :since"),
            {"u": user_id, "since": since})
        return [{"confidence": int(r["confidence"]), "score": float(r["score"]),
                 "max_score": float(r["max_score"])} for r in rows.mappings()]
