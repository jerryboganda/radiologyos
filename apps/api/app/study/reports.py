"""Weekly report use cases: build and store last week's report, read the latest.

The worker calls ``store_weekly_report`` on Monday morning in the user's time
zone (``app.weekly_reports_due``); the API only reads. Everything is computed
in code from reviews, attempts, and the planner's signals: no model is called,
no study text is stored, and no pass probability is derived.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from apps.api.app.study.ports import StudyRepo
from apps.api.app.study.service import (
    NotFound,
    days_remaining,
    local_day,
    minutes_for,
    require_profile,
    zone_for,
)
from apps.api.app.study.signals import TopicRow, topic_rows
from packages.study import fsrs
from packages.study.planner import phase_for, priority
from packages.study.report import (
    REPORT_VERSION,
    AttemptEvent,
    ReviewEvent,
    SystemStatus,
    WeekInputs,
    build_report,
)


def previous_week_start(profile: dict[str, Any], now: datetime) -> date:
    """Monday of the last complete local week."""
    today = local_day(profile, now)
    return today - timedelta(days=today.weekday() + 7)


def _status(row: TopicRow) -> SystemStatus:
    return SystemStatus(
        code=row.node.code, title=row.node.title, mastery=row.mastery.score,
        band=row.mastery.band, priority=round(priority(row.signal, row.weight), 6),
        has_material=bool(row.cards or row.questions),
        recent_lapse=row.signal.recent_lapse, started=row.signal.days_untouched is not None,
    )


def _planned(profile: dict[str, Any], week_start: date) -> int:
    days = [week_start + timedelta(days=i) for i in range(7)]
    return sum(minutes_for(profile, day) for day in days if day < profile["exam_date"])


async def build_weekly_report(
    repo: StudyRepo, user_id: UUID, now: datetime, week_start: date | None = None
) -> tuple[date, dict[str, Any]]:
    profile = await require_profile(repo, user_id)
    zone = zone_for(profile)
    start_day = week_start or previous_week_start(profile, now)
    start = datetime.combine(start_day, time.min, tzinfo=zone)
    end = datetime.combine(start_day + timedelta(days=7), time.min, tzinfo=zone)
    reviews = [ReviewEvent(r["reviewed_at"], int(r["rating"]), str(r["state_before"]))
               for r in await repo.reviews_between(user_id, start, end)]
    attempts = [AttemptEvent(a["created_at"], float(a["score"]), float(a["max_score"]))
                for a in await repo.attempts_between(user_id, start, end)]
    rows, weights = await topic_rows(repo, user_id, now, profile)
    remaining = days_remaining(profile, now)
    report = build_report(WeekInputs(
        week_start=start_day, zone=zone, reviews=reviews, attempts=attempts,
        systems=[_status(row) for row in rows],
        target_retention=fsrs.retention_for(remaining),
        planned_minutes=_planned(profile, start_day), days_remaining=remaining,
        phase=phase_for(remaining), weight_policy=weights.policy,
    ))
    return start_day, report


async def store_weekly_report(
    repo: StudyRepo, user_id: UUID, now: datetime, week_start: date | None = None
) -> date:
    """Build and upsert one report (idempotent per user and week)."""
    start_day, report = await build_weekly_report(repo, user_id, now, week_start)
    await repo.save_report(user_id, start_day, REPORT_VERSION, report)
    await repo.commit()
    return start_day


async def latest_report(repo: StudyRepo, user_id: UUID) -> dict[str, Any]:
    row = await repo.latest_report(user_id)
    if row is None:
        raise NotFound("no weekly report yet")
    return {**row["report"], "generated_at": row["generated_at"]}
