from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast
from uuid import UUID

from apps.api.app.preview.knowledge import ensure_knowledge
from apps.api.app.preview.state import PreviewAudit, PreviewCard, PreviewState

_NODES = (
    ("CHEST", "Chest imaging"),
    ("NEURO", "Neuroradiology"),
    ("CARDIAC", "Cardiac imaging"),
    ("ABDOMEN", "Abdominal imaging"),
    ("MSK", "Musculoskeletal imaging"),
)


def phase_for(days_remaining: int) -> str:
    if days_remaining > 180:
        return "coverage"
    if days_remaining >= 90:
        return "coverage_consolidation"
    if days_remaining >= 30:
        return "consolidation"
    if days_remaining >= 7:
        return "exam_mode"
    return "taper"


def _priority(mastery: float, age_days: int, conflict: bool) -> float:
    return (1.0 - mastery) * (1.5 if conflict else 1.0) * (1.0 + min(age_days, 30) / 30)


def _make_cards(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> None:
    if state.cards(tenant_id, owner_id):
        return
    now = state.now()
    for index, (code, title) in enumerate(_NODES, start=1):
        state.add_card(
            PreviewCard(
                id=state.new_id(),
                tenant_id=tenant_id,
                owner_id=owner_id,
                prompt=f"Synthetic recall: {title}",
                answer=f"Synthetic answer for {code}.",
                citation={
                    "source_id": "synthetic",
                    "page_no": 1,
                    "block_id": f"synthetic-{index}",
                    "bbox": [0.0, 0.0, 0.0, 0.0],
                },
                due_at=now,
            )
        )


def _plan(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    exam_date: date,
    hours_per_week: int,
    session_minutes: int,
    plan_version: int,
) -> dict[str, Any]:
    days_remaining = max((exam_date - state.now().date()).days, 0)
    items: list[dict[str, Any]] = []
    for index, (code, title) in enumerate(_NODES):
        mastery = min(0.15 * index, 0.6)
        items.append(
            {
                "curriculum_code": code,
                "title": title,
                "priority": round(_priority(mastery, index * 3, index == 0), 4),
                "mastery": round(mastery, 4),
                "band": "weak" if mastery < 0.5 else "learning",
                "reason": "Synthetic preview priority; no exam weight was inferred.",
            }
        )
    items.sort(key=lambda item: (-float(item["priority"]), str(item["curriculum_code"])))
    return {
        "plan_id": str(state.new_id()),
        "plan_version": plan_version,
        "exam_date": exam_date.isoformat(),
        "timezone": "UTC",
        "hours_per_week": hours_per_week,
        "session_minutes": session_minutes,
        "days_remaining": days_remaining,
        "phase": phase_for(days_remaining),
        "priority": items,
        "baseline_status": "not_implemented",
        "weight_policy": "equal_synthetic_preview",
        "notice": "Non-release synthetic preview; not an exam blueprint or pass prediction.",
    }


def create_plan(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    exam_date: date,
    hours_per_week: int,
    session_minutes: int,
) -> dict[str, Any]:
    ensure_knowledge(state, tenant_id, owner_id)
    _make_cards(state, tenant_id, owner_id)
    plan = _plan(state, tenant_id, owner_id, exam_date, hours_per_week, session_minutes, 1)
    state.set_plan(tenant_id, owner_id, plan)
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="plan.created",
            target_type="plan",
            target_id=str(plan["plan_id"]),
            created_at=state.now(),
        )
    )
    return plan


def get_plan(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> dict[str, Any] | None:
    return cast(dict[str, Any] | None, state.plan(tenant_id, owner_id))


def replan(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> dict[str, Any]:
    current = cast(dict[str, Any] | None, state.plan(tenant_id, owner_id))
    if current is None:
        raise ValueError("onboarding required")
    plan = _plan(
        state,
        tenant_id,
        owner_id,
        date.fromisoformat(str(current["exam_date"])),
        int(current["hours_per_week"]),
        int(current["session_minutes"]),
        int(current["plan_version"]) + 1,
    )
    state.set_plan(tenant_id, owner_id, plan)
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="plan.replanned",
            target_type="plan",
            target_id=str(plan["plan_id"]),
            created_at=state.now(),
        )
    )
    return plan


def today(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> dict[str, Any]:
    plan = cast(dict[str, Any] | None, state.plan(tenant_id, owner_id))
    if plan is None:
        raise ValueError("onboarding required")
    minutes = int(plan["session_minutes"])
    review = max(round(minutes * 0.2), 1)
    learn = max(round(minutes * 0.5), 1)
    test = max(minutes - review - learn, 1)
    cards = state.cards(tenant_id, owner_id)
    due_ids = tuple(str(card.id) for card in cards if card.due_at <= state.now())
    priority = list(plan["priority"])
    return {
        "session_id": str(state.new_id()),
        "plan_version": plan["plan_version"],
        "days_remaining": plan["days_remaining"],
        "phase": plan["phase"],
        "blocks": (
            {"kind": "review", "duration_minutes": review, "card_ids": due_ids[:10]},
            {
                "kind": "learn",
                "duration_minutes": learn,
                "curriculum_codes": tuple(str(item["curriculum_code"]) for item in priority[:3]),
            },
            {"kind": "test", "duration_minutes": test, "question_ids": ()},
        ),
        "omitted_blocks": ("viva",),
    }


def due_cards(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    limit: int,
) -> list[PreviewCard]:
    return sorted(
        [card for card in state.cards(tenant_id, owner_id) if card.due_at <= state.now()],
        key=lambda card: (card.due_at, str(card.id)),
    )[:limit]


def review_card(
    state: PreviewState,
    tenant_id: UUID,
    owner_id: UUID,
    card_id: UUID,
    rating: int,
) -> PreviewCard:
    card = state.card(tenant_id, card_id)
    if card is None or card.owner_id != owner_id:
        raise LookupError("card not found")
    if rating not in {1, 2, 3, 4}:
        raise ValueError("rating must be between 1 and 4")
    if rating == 1:
        stability = max(card.stability * 0.5, 1.0)
        due = state.now() + timedelta(minutes=10)
        difficulty = min(card.difficulty + 0.8, 10.0)
        # Read the new value without mutating the card instance held in state.
        lapses = card.lapses + 1
    elif rating == 2:
        stability = max(card.stability * 0.8, 1.0)
        due = state.now() + timedelta(days=1)
        difficulty = min(card.difficulty + 0.3, 10.0)
        lapses = card.lapses
    else:
        stability = max(card.stability * (1.5 if rating == 3 else 2.0), 1.0)
        due = state.now() + timedelta(days=stability)
        difficulty = max(card.difficulty - (0.1 if rating == 3 else 0.5), 1.0)
        lapses = card.lapses
    updated = PreviewCard(
        id=card.id,
        tenant_id=card.tenant_id,
        owner_id=card.owner_id,
        prompt=card.prompt,
        answer=card.answer,
        citation=card.citation,
        due_at=due,
        stability=stability,
        difficulty=difficulty,
        reps=card.reps + 1,
        lapses=lapses,
    )
    state.add_card(updated)
    state.add_audit(
        PreviewAudit(
            tenant_id=tenant_id,
            actor_id=owner_id,
            action="card.reviewed",
            target_type="card",
            target_id=str(card_id),
            created_at=state.now(),
        )
    )
    return updated


def mastery(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> dict[str, Any]:
    attempts = state.attempts(tenant_id, owner_id)
    correct = sum(1 for attempt in attempts if attempt.correct)
    accuracy = correct / len(attempts) if attempts else 0.0
    cards = state.cards(tenant_id, owner_id)
    retrievability = min(sum(card.stability for card in cards) / max(len(cards), 1) / 10, 1.0)
    coverage = 0.5 if cards else 0.0
    score = 0.5 * accuracy + 0.3 * retrievability + 0.2 * coverage
    return {
        "version": 1,
        "method": "synthetic_proxy_v1",
        "nodes": [
            {
                "curriculum_code": code,
                "title": title,
                "score": round(score, 4),
                "band": "weak" if score < 0.5 else "learning" if score < 0.8 else "mastered",
                "accuracy": round(accuracy, 4),
                "retrievability": round(retrievability, 4),
                "coverage": round(coverage, 4),
                "attempt_count": len(attempts),
                "due_cards": sum(card.due_at <= state.now() for card in cards),
                "lapses": sum(card.lapses for card in cards),
            }
            for code, title in _NODES
        ],
    }
