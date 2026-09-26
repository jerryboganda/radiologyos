"""Recompute item statistics for one owner and retire failing items.

Runs inside the owner's tenant context (API on demand, or the worker after an
exam finishes grading), so no cross-tenant read path is needed. Retirement is
recorded on the question (``status_reason``), in ``item_stats``, and in
``audit_log`` with ids and reason codes only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.assessment.stats import AttemptRow, compute_stats, decision, retirement_reason
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_UPSERT = text(
    """
    INSERT INTO item_stats (tenant_id, question_id, user_id, attempts, correct, p_value,
                            discrimination, discrimination_n, decision, reason, last_computed)
    VALUES (:t, :q, :u, :attempts, :correct, :p, :d, :dn, :decision, :reason, now())
    ON CONFLICT (tenant_id, question_id) DO UPDATE SET
        attempts = EXCLUDED.attempts, correct = EXCLUDED.correct, p_value = EXCLUDED.p_value,
        discrimination = EXCLUDED.discrimination, discrimination_n = EXCLUDED.discrimination_n,
        decision = EXCLUDED.decision, reason = EXCLUDED.reason, last_computed = now()
    """
)


async def _attempt_rows(session: AsyncSession, user_id: UUID) -> list[AttemptRow]:
    rows = await session.execute(
        text(
            "SELECT a.question_id, a.exam_id, a.score, a.max_score FROM attempts a "
            "JOIN questions q ON q.id = a.question_id AND q.tenant_id = a.tenant_id "
            "WHERE q.user_id = :u"
        ),
        {"u": user_id},
    )
    return [
        AttemptRow(str(r[0]), str(r[1]) if r[1] is not None else None, float(r[2]), float(r[3]))
        for r in rows
    ]


async def _retire(session: AsyncSession, user_id: UUID, question_id: str, reason: str) -> bool:
    row = await session.execute(
        text(
            "UPDATE questions SET status = 'retired', status_reason = :r, "
            "status_changed_at = now() WHERE id = :q AND user_id = :u AND status = 'active' "
            "RETURNING id"
        ),
        {"q": UUID(question_id), "u": user_id, "r": f"stats:{reason}"},
    )
    return row.first() is not None


async def recompute(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    """Upsert stats for every attempted item the owner has; retire failing active items."""
    stats = compute_stats(await _attempt_rows(session, user_id))
    if stats:
        await session.execute(_UPSERT, [
            {"t": tenant_id, "q": UUID(s.question_id), "u": user_id, "attempts": s.attempts,
             "correct": s.correct, "p": s.p_value, "d": s.discrimination,
             "dn": s.discrimination_n, "decision": decision(s), "reason": retirement_reason(s)}
            for s in stats.values()
        ])
    retired: list[dict[str, Any]] = []
    principal = Principal(user_id=user_id, tenant_id=tenant_id)
    for stat in stats.values():
        reason = retirement_reason(stat)
        if reason and await _retire(session, user_id, stat.question_id, reason):
            retired.append({"question_id": stat.question_id, "reason": reason})
            await audit(session, principal, "question.retired", "question", stat.question_id,
                        {"reason": reason, "attempts": stat.attempts})
    return {
        "computed": len(stats),
        "retired": retired,
        "stats": [
            {"question_id": s.question_id, "attempts": s.attempts, "correct": s.correct,
             "p_value": s.p_value, "discrimination": s.discrimination,
             "discrimination_n": s.discrimination_n, "decision": decision(s),
             "reason": retirement_reason(s)}
            for s in stats.values()
        ],
    }
