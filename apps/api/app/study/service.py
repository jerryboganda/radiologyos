"""Study use cases: onboarding profile, daily plan, cards, reviews, progress.

Pure scheduling and planning live in ``packages.study``; this module loads
state through a repository, applies the domain rules, and commits once.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.api.app.study.ports import StudyRepo
from apps.api.app.study.signals import (
    TopicRow,
    curriculum_codes,
    curriculum_systems,
    topic_rows,
)
from packages.study import fsrs
from packages.study.planner import (
    NEW_CARD_CAP,
    PLANNER_VERSION,
    DayInputs,
    build_plan,
    phase_for,
    priority,
)

__all__ = ["StudyRepo", "TopicRow", "curriculum_codes", "curriculum_systems", "topic_rows"]

NOTICE = "Rules-based plan and mastery bands. No pass probability is shown until validated."


class StudyError(Exception):
    status_code = 400


class OnboardingRequired(StudyError):
    status_code = 409


class NotFound(StudyError):
    status_code = 404


class Invalid(StudyError):
    status_code = 422


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone_for(profile: dict[str, Any] | None) -> ZoneInfo:
    name = str(profile["timezone"]) if profile else "UTC"
    return ZoneInfo(name) if valid_timezone(name) else ZoneInfo("UTC")


def local_day(profile: dict[str, Any] | None, now: datetime) -> date:
    return now.astimezone(zone_for(profile)).date()


def day_start(profile: dict[str, Any] | None, now: datetime) -> datetime:
    return datetime.combine(local_day(profile, now), time.min, tzinfo=zone_for(profile))


def minutes_for(profile: dict[str, Any], day: date) -> int:
    key = "weekend_minutes" if day.weekday() >= 5 else "weekday_minutes"
    value = profile.get(key)
    return int(profile["daily_minutes"] if value is None else value)


def days_remaining(profile: dict[str, Any], now: datetime) -> int:
    exam: date = profile["exam_date"]
    return max((exam - local_day(profile, now)).days, 0)


async def require_profile(repo: StudyRepo, user_id: UUID) -> dict[str, Any]:
    profile = await repo.get_profile(user_id)
    if profile is None:
        raise OnboardingRequired("set your exam date first")
    return profile


async def save_profile(
    repo: StudyRepo, user_id: UUID, data: dict[str, Any], now: datetime
) -> dict[str, Any]:
    if not valid_timezone(str(data["timezone"])):
        raise Invalid("unknown time zone")
    today = local_day(data, now)
    if data["exam_date"] <= today:
        raise Invalid("exam date must be in the future")
    profile = await repo.save_profile(user_id, data)
    await repo.delete_plans_from(user_id, today)
    await repo.commit()
    return profile


def _new_limit(counts: dict[str, int], phase: str) -> int:
    if phase == "taper":
        return 0
    return max(min(counts["new"], NEW_CARD_CAP - counts["new_today"]), 0)


async def today_plan(
    repo: StudyRepo, user_id: UUID, now: datetime, refresh: bool = False
) -> dict[str, Any]:
    plan = await ensure_plan(repo, user_id, now, refresh)
    await repo.commit()
    return plan


async def ensure_plan(
    repo: StudyRepo, user_id: UUID, now: datetime, refresh: bool = False
) -> dict[str, Any]:
    """The cached plan for the local day, else a fresh one saved in this transaction."""
    profile = await require_profile(repo, user_id)
    day = local_day(profile, now)
    cached = None if refresh else await repo.get_plan(user_id, day)
    if cached is not None and cached["plan_version"] == PLANNER_VERSION:
        return {**cached["detail"], "blocks": cached["blocks"],
                "generated_at": cached["generated_at"]}
    counts = await repo.counts(user_id, now, day_start(profile, now))
    rows, weights = await topic_rows(repo, user_id, now, profile)
    phase = phase_for(days_remaining(profile, now))
    plan = build_plan(DayInputs(
        today=day, exam_date=profile["exam_date"], minutes=minutes_for(profile, day),
        due_count=counts["due"], new_available=_new_limit(counts, phase),
        topics=[row.signal for row in rows], exam_targets=tuple(profile["exam_targets"]),
        weight_policy=weights.policy, weight_targets=weights.targets,
    ))
    generated = await repo.save_plan(user_id, plan)
    return {**plan, "generated_at": generated}


async def plan_for_tomorrow(repo: StudyRepo, user_id: UUID, now: datetime) -> dict[str, Any]:
    """Nightly replan: build tomorrow's plan as of local midnight.

    Idempotent per (user, date, plan_version): a current-version plan for that
    date is returned unchanged.
    """
    profile = await require_profile(repo, user_id)
    tomorrow = local_day(profile, now) + timedelta(days=1)
    at = datetime.combine(tomorrow, time.min, tzinfo=zone_for(profile))
    return await today_plan(repo, user_id, at)


def citation_for(chunk: dict[str, Any]) -> dict[str, Any]:
    return {"source_id": str(chunk["source_id"]), "source_title": chunk["source_title"],
            "chunk_id": str(chunk["id"]), "page_from": chunk["page_from"],
            "page_to": chunk["page_to"], "block_refs": chunk["block_refs"]}


def card_from_chunk(chunk: dict[str, Any], fields: dict[str, Any], origin: str,
                    now: datetime) -> dict[str, Any]:
    if fields["curriculum_code"] not in curriculum_codes():
        raise Invalid("unknown curriculum code")
    return {"source_id": chunk["source_id"], "source_chunk_id": chunk["id"],
            "curriculum_code": fields["curriculum_code"], "topic": fields["topic"],
            "front": fields["front"], "back": fields["back"], "origin": origin,
            "citation": citation_for(chunk), "due_at": now}


async def create_card(
    repo: StudyRepo, user_id: UUID, fields: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Create a card whose citation is built from a chunk the caller owns."""
    chunk = await repo.chunk_for_user(user_id, fields["chunk_id"])
    if chunk is None:
        raise NotFound("chunk not found")
    row = await repo.insert_card(user_id, card_from_chunk(chunk, fields, "manual", now))
    await repo.commit()
    return row


async def due_cards(
    repo: StudyRepo, user_id: UUID, now: datetime, limit: int
) -> list[dict[str, Any]]:
    profile = await repo.get_profile(user_id)
    counts = await repo.counts(user_id, now, day_start(profile, now))
    phase = phase_for(days_remaining(profile, now)) if profile else "coverage"
    return await repo.due_cards(user_id, now, limit, _new_limit(counts, phase))


async def review_card(
    repo: StudyRepo, user_id: UUID, card_id: UUID, rating: int, now: datetime
) -> dict[str, Any]:
    card = await repo.get_card(user_id, card_id)
    if card is None:
        raise NotFound("card not found")
    profile = await repo.get_profile(user_id)
    retention = fsrs.retention_for(days_remaining(profile, now) if profile else None)
    memory = fsrs.CardMemory(
        state=card["state"], stability=float(card["stability"]),
        difficulty=float(card["difficulty"]), due_at=card["due_at"],
        last_review_at=card["last_review_at"], reps=card["reps"], lapses=card["lapses"])
    try:
        outcome = fsrs.review(memory, rating, now, retention)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    new = outcome.card
    updated = {"id": card["id"], "state": new.state, "stability": new.stability,
               "difficulty": new.difficulty, "due_at": new.due_at,
               "last_review_at": new.last_review_at, "reps": new.reps, "lapses": new.lapses}
    review = {"rating": rating, "reviewed_at": now, "elapsed_days": outcome.elapsed_days,
              "scheduled_days": outcome.scheduled_days, "state_before": memory.state,
              "retrievability": outcome.retrievability}
    row = await repo.apply_review(user_id, updated, review)
    if rating == fsrs.Rating.AGAIN and row.get("review_id") is not None:
        await repo.record_lapse(user_id, row, row["review_id"], now)
    await repo.commit()
    return {"card": row, "scheduled_days": outcome.scheduled_days, "retention": retention}


async def progress(repo: StudyRepo, user_id: UUID, now: datetime) -> dict[str, Any]:
    profile = await require_profile(repo, user_id)
    remaining = days_remaining(profile, now)
    counts = await repo.counts(user_id, now, day_start(profile, now))
    rows, weights = await topic_rows(repo, user_id, now, profile)
    return {
        "exam_date": profile["exam_date"], "days_remaining": remaining,
        "phase": phase_for(remaining), "retention": fsrs.retention_for(remaining),
        "cards": counts["cards"], "due_now": counts["due"], "new_cards": counts["new"],
        "reviews_total": counts["reviews"], "reviews_today": counts["reviews_today"],
        "weight_policy": weights.policy, "weight_targets": list(weights.targets),
        "topics": [
            {"code": r.node.code, "title": r.node.title, "mastery": r.mastery.score,
             "band": r.mastery.band, "accuracy": r.mastery.accuracy,
             "retrievability": r.mastery.retrievability, "coverage": r.mastery.coverage,
             "cards": r.cards, "lapses": r.lapses, "questions": r.questions,
             "attempts": r.attempts, "weight": r.weight,
             "priority": round(priority(r.signal, r.weight), 6)}
            for r in rows
        ],
        "notice": NOTICE,
    }
