"""Resolve each question's curriculum system from the chunks it cites.

Accepted curriculum mappings and the user's cards on those chunks vote; the
most common system code wins (ties by code). Shared by the planner signals and
blueprint paper assembly. The CTE is bound to ``:u`` (the owning user).
"""

from __future__ import annotations

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
