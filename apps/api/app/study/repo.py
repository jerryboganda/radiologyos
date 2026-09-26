"""SQL access for the study engine.

Every query runs in the caller's transaction-local tenant session (RLS) and is
additionally scoped to the calling user. ``app.tenant_id`` is transaction-local,
so callers commit once, at the end of a request.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from apps.api.app.study.depth_sql import StudyDepthSql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROFILE_COLUMNS = (
    "exam_date, exam_targets, daily_minutes, weekday_minutes, weekend_minutes, timezone, "
    "reminder, updated_at"
)
CARD_COLUMNS = (
    "id, curriculum_code, topic, front, back, origin, source_id, source_chunk_id, citation, "
    "state, stability, difficulty, due_at, last_review_at, reps, lapses, created_at"
)
CHUNK_SELECT = """
    SELECT c.id, c.source_id, s.title AS source_title, c.page_from, c.page_to,
           c.heading, c.text, c.block_refs
    FROM chunks c JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
    WHERE s.uploaded_by = :u AND s.deleted_at IS NULL
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class SqlStudyRepo(StudyDepthSql):
    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def _one(self, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        row = (await self.session.execute(text(sql), params)).mappings().first()
        return dict(row) if row else None

    async def _all(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await self.session.execute(text(sql), params)
        return [dict(row) for row in rows.mappings()]

    async def commit(self) -> None:
        await self.session.commit()

    async def release(self) -> None:
        """End the current transaction before a long model call."""
        await self.session.commit()

    async def rebind(self) -> None:
        """Re-apply the transaction-local tenant setting after ``release``."""
        await self.session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(self.tenant_id)}
        )

    async def get_profile(self, user_id: UUID) -> dict[str, Any] | None:
        return await self._one(
            f"SELECT {PROFILE_COLUMNS} FROM study_profiles WHERE user_id = :u", {"u": user_id})  # nosec B608 - constant column list; all values are bound parameters

    async def save_profile(self, user_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        params = {**data, "u": user_id, "t": self.tenant_id, "reminder": _json(data["reminder"]),
                  "exam_targets": list(data["exam_targets"])}
        row = await self._one(
            f"""
            INSERT INTO study_profiles (tenant_id, user_id, exam_date, exam_targets,
                daily_minutes, weekday_minutes, weekend_minutes, timezone, reminder)
            VALUES (:t, :u, :exam_date, :exam_targets, :daily_minutes,
                :weekday_minutes, :weekend_minutes, :timezone, CAST(:reminder AS jsonb))
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                exam_date = EXCLUDED.exam_date, exam_targets = EXCLUDED.exam_targets,
                daily_minutes = EXCLUDED.daily_minutes,
                weekday_minutes = EXCLUDED.weekday_minutes,
                weekend_minutes = EXCLUDED.weekend_minutes,
                timezone = EXCLUDED.timezone, reminder = EXCLUDED.reminder
            RETURNING {PROFILE_COLUMNS}
            """,  # nosec B608 - constant column list; all values are bound parameters
            params,
        )
        assert row is not None
        return row

    async def delete_plans_from(self, user_id: UUID, day: date) -> None:
        await self.session.execute(
            text("DELETE FROM study_plans WHERE user_id = :u AND plan_date >= :d"),
            {"u": user_id, "d": day})

    async def get_plan(self, user_id: UUID, day: date) -> dict[str, Any] | None:
        return await self._one(
            "SELECT plan_version, blocks, detail, generated_at FROM study_plans "
            "WHERE user_id = :u AND plan_date = :d", {"u": user_id, "d": day})

    async def save_plan(self, user_id: UUID, plan: dict[str, Any]) -> datetime:
        detail = {k: v for k, v in plan.items() if k != "blocks"}
        row = await self._one(
            """
            INSERT INTO study_plans (tenant_id, user_id, plan_date, phase, days_remaining,
                minutes, plan_version, blocks, detail)
            VALUES (:t, :u, :d, :phase, :days, :minutes, :version,
                CAST(:blocks AS jsonb), CAST(:detail AS jsonb))
            ON CONFLICT (tenant_id, user_id, plan_date) DO UPDATE SET
                phase = EXCLUDED.phase, days_remaining = EXCLUDED.days_remaining,
                minutes = EXCLUDED.minutes, plan_version = EXCLUDED.plan_version,
                blocks = EXCLUDED.blocks, detail = EXCLUDED.detail, generated_at = now()
            RETURNING generated_at
            """,
            {"u": user_id, "t": self.tenant_id, "d": date.fromisoformat(plan["plan_date"]),
             "phase": plan["phase"], "days": plan["days_remaining"], "minutes": plan["minutes"],
             "version": plan["plan_version"], "blocks": _json(plan["blocks"]),
             "detail": _json(detail)},
        )
        assert row is not None
        generated: datetime = row["generated_at"]
        return generated

    async def chunk_for_user(self, user_id: UUID, chunk_id: UUID) -> dict[str, Any] | None:
        return await self._one(CHUNK_SELECT + " AND c.id = :c", {"u": user_id, "c": chunk_id})

    async def chunks_for_user(
        self, user_id: UUID, source_id: UUID | None, chunk_ids: Sequence[UUID], limit: int
    ) -> list[dict[str, Any]]:
        if chunk_ids:
            return await self._all(CHUNK_SELECT + " AND c.id = ANY(:ids) ORDER BY c.chunk_no",
                                   {"u": user_id, "ids": list(chunk_ids)})
        return await self._all(
            CHUNK_SELECT + """ AND c.source_id = :s AND NOT EXISTS (
                SELECT 1 FROM cards k WHERE k.source_chunk_id = c.id AND k.user_id = :u)
              ORDER BY c.chunk_no LIMIT :n""",  # nosec B608 - constant column list; all values are bound parameters
            {"u": user_id, "s": source_id, "n": limit})

    async def insert_card(self, user_id: UUID, card: dict[str, Any]) -> dict[str, Any]:
        row = await self._one(
            f"""
            INSERT INTO cards (tenant_id, user_id, source_id, source_chunk_id, curriculum_code,
                topic, front, back, origin, citation, due_at)
            VALUES (:t, :u, :source_id, :source_chunk_id,
                :curriculum_code, :topic, :front, :back, :origin,
                CAST(:citation AS jsonb), :due_at)
            RETURNING {CARD_COLUMNS}
            """,  # nosec B608 - constant column list; all values are bound parameters
            {**card, "u": user_id, "t": self.tenant_id, "citation": _json(card["citation"])},
        )
        assert row is not None
        return row

    async def get_card(self, user_id: UUID, card_id: UUID) -> dict[str, Any] | None:
        return await self._one(
            f"SELECT {CARD_COLUMNS} FROM cards WHERE id = :c AND user_id = :u",  # nosec B608 - constant column list; all values are bound parameters
            {"c": card_id, "u": user_id})

    async def due_cards(
        self, user_id: UUID, now: datetime, limit: int, new_limit: int
    ) -> list[dict[str, Any]]:
        due = await self._all(
            f"SELECT {CARD_COLUMNS} FROM cards WHERE user_id = :u AND state <> 'new' "  # nosec B608 - constant column list; all values are bound parameters
            "AND due_at <= :now ORDER BY due_at, id LIMIT :n",
            {"u": user_id, "now": now, "n": limit})
        room = min(new_limit, limit - len(due))
        if room <= 0:
            return due
        fresh = await self._all(
            f"SELECT {CARD_COLUMNS} FROM cards WHERE user_id = :u AND state = 'new' "  # nosec B608 - constant column list; all values are bound parameters
            "ORDER BY created_at, id LIMIT :n", {"u": user_id, "n": room})
        return due + fresh

    async def counts(self, user_id: UUID, now: datetime, day_start: datetime) -> dict[str, int]:
        row = await self._one(
            """
            SELECT
              (SELECT count(*) FROM cards WHERE user_id = :u) AS cards,
              (SELECT count(*) FROM cards WHERE user_id = :u AND state <> 'new'
                 AND due_at <= :now) AS due,
              (SELECT count(*) FROM cards WHERE user_id = :u AND state = 'new') AS new,
              (SELECT count(*) FROM card_reviews WHERE user_id = :u) AS reviews,
              (SELECT count(*) FROM card_reviews WHERE user_id = :u
                 AND reviewed_at >= :start) AS reviews_today,
              (SELECT count(*) FROM card_reviews WHERE user_id = :u
                 AND reviewed_at >= :start AND state_before = 'new') AS new_today
            """,
            {"u": user_id, "now": now, "start": day_start},
        )
        assert row is not None
        return {key: int(value) for key, value in row.items()}

    async def apply_review(
        self, user_id: UUID, card: dict[str, Any], review: dict[str, Any]
    ) -> dict[str, Any]:
        row = await self._one(
            f"""
            UPDATE cards SET state = :state, stability = :stability, difficulty = :difficulty,
                due_at = :due_at, last_review_at = :last_review_at, reps = :reps,
                lapses = :lapses
            WHERE id = :id AND user_id = :u
            RETURNING {CARD_COLUMNS}
            """,  # nosec B608 - constant column list; all values are bound parameters
            {**card, "u": user_id},
        )
        assert row is not None
        await self.session.execute(
            text(
                """
                INSERT INTO card_reviews (tenant_id, user_id, card_id, rating, reviewed_at,
                    elapsed_days, scheduled_days, state_before, stability_after,
                    difficulty_after, retrievability)
                VALUES (:t, :u, :id, :rating, :reviewed_at, :elapsed_days,
                    :scheduled_days, :state_before, :stability, :difficulty, :retrievability)
                """
            ),
            {**review, "u": user_id, "t": self.tenant_id, "id": card["id"],
             "stability": card["stability"], "difficulty": card["difficulty"]},
        )
        return row

    async def topic_cards(self, user_id: UUID) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT curriculum_code, state, stability, last_review_at, reps, lapses "
            "FROM cards WHERE user_id = :u", {"u": user_id})

    async def reviews_since(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        return await self._all(
            "SELECT k.curriculum_code, r.rating, r.reviewed_at FROM card_reviews r "
            "JOIN cards k ON k.id = r.card_id AND k.tenant_id = r.tenant_id "
            "WHERE r.user_id = :u AND r.reviewed_at >= :since", {"u": user_id, "since": since})
