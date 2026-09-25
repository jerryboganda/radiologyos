"""M4 eval gate: onboarding, planner, Today, and spaced-repetition scheduling.

Covers slices P and Q of the A-Z queue:
  P  exam-date onboarding, baseline status, planner, phases, Today runner
  Q  FSRS-style cards, mastery, scheduling, and idempotency

The planner is explicitly synthetic: it must not present itself as an exam
blueprint or a pass prediction, and these tests pin that down.

All content is synthetic.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

import pytest
from apps.api.app.preview.learning import (
    create_plan,
    due_cards,
    get_plan,
    mastery,
    phase_for,
    replan,
    review_card,
    today,
)
from evals.checks._harness import OWNER_A, OWNER_B, TENANT_A, TENANT_B, new_state, seed

# Fixed reference point so phase boundaries are asserted, not assumed.
DAYS = 365


def planned(days: int = DAYS, hours: int = 10, minutes: int = 60):
    state = new_state()
    seed(state)
    plan = create_plan(
        state,
        TENANT_A,
        OWNER_A,
        exam_date=date.today() + timedelta(days=days),
        hours_per_week=hours,
        session_minutes=minutes,
    )
    return state, plan


# ---------------------------------------------------------------- slice P


def test_today_requires_onboarding_first() -> None:
    state = new_state()
    seed(state)
    with pytest.raises(ValueError, match="onboarding required"):
        today(state, TENANT_A, OWNER_A)
    with pytest.raises(ValueError, match="onboarding required"):
        replan(state, TENANT_A, OWNER_A)


def test_onboarding_then_today_closes_the_loop() -> None:
    state, plan = planned()
    session = today(state, TENANT_A, OWNER_A)

    assert session["plan_version"] == plan["plan_version"]
    assert session["phase"] == plan["phase"]
    assert session["days_remaining"] == plan["days_remaining"]
    assert [b["kind"] for b in session["blocks"]] == ["review", "learn", "test"]


def test_today_block_durations_sum_to_the_configured_session() -> None:
    for minutes in (20, 45, 60, 90):
        state, plan = planned(minutes=minutes)
        session = today(state, TENANT_A, OWNER_A)
        total = sum(int(b["duration_minutes"]) for b in session["blocks"])
        assert total == minutes, f"{minutes} minute session summed to {total}"


def test_today_omits_the_viva_block_rather_than_faking_it() -> None:
    state, _ = planned()
    session = today(state, TENANT_A, OWNER_A)

    assert "viva" in session["omitted_blocks"]
    assert all(b["kind"] != "viva" for b in session["blocks"])


@pytest.mark.parametrize(
    ("days_remaining", "expected"),
    [
        (365, "coverage"),
        (181, "coverage"),
        (180, "coverage_consolidation"),
        (90, "coverage_consolidation"),
        (89, "consolidation"),
        (30, "consolidation"),
        (29, "exam_mode"),
        (7, "exam_mode"),
        (6, "taper"),
        (0, "taper"),
    ],
)
def test_phase_boundaries_are_exact(days_remaining: int, expected: str) -> None:
    """phase_for is a pure function, so boundaries are asserted directly.

    Asserting through create_plan would make the test depend on the machine's
    timezone, because the plan derives days_remaining from the UTC clock while
    the exam date is built from the local calendar.
    """
    assert phase_for(days_remaining) == expected


def test_plan_phase_agrees_with_its_own_days_remaining() -> None:
    for days in (365, 180, 90, 30, 7, 1):
        state, plan = planned(days=days)
        assert plan["phase"] == phase_for(int(plan["days_remaining"]))
        assert plan["days_remaining"] >= 0
        assert today(state, TENANT_A, OWNER_A)["phase"] == plan["phase"]


def test_a_past_exam_date_clamps_to_zero_days() -> None:
    state = new_state()
    seed(state)
    plan = create_plan(
        state,
        TENANT_A,
        OWNER_A,
        exam_date=date.today() - timedelta(days=30),
        hours_per_week=10,
        session_minutes=60,
    )
    assert plan["days_remaining"] == 0
    assert plan["phase"] == "taper"


def test_planner_never_claims_to_be_a_blueprint_or_prediction() -> None:
    """Curriculum weight and pass prediction are human-decision gated."""
    _, plan = planned()
    assert plan["weight_policy"] == "equal_synthetic_preview"
    assert plan["baseline_status"] == "not_implemented"
    assert "not an exam blueprint" in plan["notice"]
    assert "pass prediction" in plan["notice"]


def test_planner_priorities_are_ordered_and_fully_represented() -> None:
    _, plan = planned()
    priority = plan["priority"]

    assert priority
    scores = [float(item["priority"]) for item in priority]
    assert scores == sorted(scores, reverse=True)
    codes = [item["curriculum_code"] for item in priority]
    assert len(codes) == len(set(codes)), "each curriculum node appears once"
    for item in priority:
        assert item["band"] in {"weak", "learning"}
        assert item["reason"]


def test_replan_bumps_the_version_and_keeps_the_exam_date() -> None:
    state, plan = planned()
    second = replan(state, TENANT_A, OWNER_A)

    assert second["plan_version"] == plan["plan_version"] + 1
    assert second["exam_date"] == plan["exam_date"]
    assert second["hours_per_week"] == plan["hours_per_week"]
    assert get_plan(state, TENANT_A, OWNER_A)["plan_version"] == second["plan_version"]


def test_onboarding_is_audited() -> None:
    state, plan = planned()
    replan(state, TENANT_A, OWNER_A)
    actions = [event.action for event in state.audit(TENANT_A)]

    assert "plan.created" in actions
    assert "plan.replanned" in actions
    assert actions.index("plan.created") < actions.index("plan.replanned")
    assert str(plan["plan_id"]) in {event.target_id for event in state.audit(TENANT_A)}


# ---------------------------------------------------------------- slice Q


def test_cards_are_created_with_the_plan_and_carry_citations() -> None:
    state, _ = planned()
    cards = state.cards(TENANT_A, OWNER_A)

    assert cards
    for card in cards:
        assert card.tenant_id == TENANT_A
        assert card.owner_id == OWNER_A
        assert card.prompt
        assert card.answer
        assert card.citation is not None


def test_cards_are_not_duplicated_by_replanning() -> None:
    state, _ = planned()
    before = len(state.cards(TENANT_A, OWNER_A))
    replan(state, TENANT_A, OWNER_A)
    replan(state, TENANT_A, OWNER_A)

    assert len(state.cards(TENANT_A, OWNER_A)) == before


def test_a_good_review_pushes_the_card_into_the_future() -> None:
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    before = state.now()

    updated = review_card(state, TENANT_A, OWNER_A, card.id, 4)

    assert updated.reps == 1
    assert updated.due_at > before
    assert updated.stability > card.stability
    assert updated.difficulty < card.difficulty


def test_a_lapse_shrinks_stability_and_schedules_a_ten_minute_retry() -> None:
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    # Build up some stability first so the shrink is observable. Snapshot the
    # values we assert on: the stored card is a live object.
    review_card(state, TENANT_A, OWNER_A, card.id, 4)
    primed = state.card(TENANT_A, card.id)
    primed_lapses, primed_stability, primed_difficulty = (
        primed.lapses,
        primed.stability,
        primed.difficulty,
    )

    lapsed = review_card(state, TENANT_A, OWNER_A, card.id, 1)

    assert lapsed.lapses == primed_lapses + 1
    assert lapsed.stability < primed_stability
    assert lapsed.difficulty > primed_difficulty
    assert lapsed.due_at - state.now() == pytest.approx(
        timedelta(minutes=10), abs=timedelta(seconds=5)
    )


def test_review_does_not_mutate_the_stored_card_in_place() -> None:
    """A review must publish a new card, never edit the live one under a caller."""
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    held = state.card(TENANT_A, card.id)
    before = (held.lapses, held.reps, held.stability)

    review_card(state, TENANT_A, OWNER_A, card.id, 1)

    assert (held.lapses, held.reps, held.stability) == before


@pytest.mark.parametrize("rating", [3, 4])
def test_higher_ratings_grow_stability_more(rating: int) -> None:
    state, _ = planned()
    a = state.cards(TENANT_A, OWNER_A)[0]
    b = state.cards(TENANT_A, OWNER_A)[1]

    updated_a = review_card(state, TENANT_A, OWNER_A, a.id, 3)
    updated_b = review_card(state, TENANT_A, OWNER_A, b.id, 4)

    assert updated_b.stability > updated_a.stability


@pytest.mark.parametrize("rating", [0, 5, -1, 99])
def test_out_of_range_ratings_are_rejected(rating: int) -> None:
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    with pytest.raises(ValueError, match="rating"):
        review_card(state, TENANT_A, OWNER_A, card.id, rating)


def test_review_refuses_a_card_owned_by_another_user() -> None:
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    with pytest.raises(LookupError):
        review_card(state, TENANT_A, OWNER_B, card.id, 4)


def test_review_refuses_an_unknown_card() -> None:
    state, _ = planned()
    with pytest.raises(LookupError):
        review_card(state, TENANT_A, OWNER_A, UUID(int=9999), 4)


def test_due_cards_respect_the_limit_and_drain_over_time() -> None:
    state, _ = planned()
    total = len(state.cards(TENANT_A, OWNER_A))

    assert len(due_cards(state, TENANT_A, OWNER_A, 2)) == 2
    assert len(due_cards(state, TENANT_A, OWNER_A, total)) == total

    # Reviewing every card out of the due queue empties it.
    for card in list(due_cards(state, TENANT_A, OWNER_A, total)):
        review_card(state, TENANT_A, OWNER_A, card.id, 4)
    assert due_cards(state, TENANT_A, OWNER_A, total) == []


def test_review_is_audited() -> None:
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    review_card(state, TENANT_A, OWNER_A, card.id, 4)

    reviewed = [e for e in state.audit(TENANT_A) if e.action == "card.reviewed"]
    assert len(reviewed) == 1
    assert reviewed[0].target_id == str(card.id)


def test_mastery_reports_a_banded_score_per_node() -> None:
    state, _ = planned()
    report = mastery(state, TENANT_A, OWNER_A)

    assert report["method"] == "synthetic_proxy_v1"
    assert report["nodes"]
    for node in report["nodes"]:
        assert 0.0 <= float(node["score"]) <= 1.0
        assert node["band"] in {"weak", "learning", "mastered"}
        assert node["attempt_count"] == 0
        assert 0 <= float(node["accuracy"]) <= 1.0
        assert 0.0 <= float(node["coverage"]) <= 1.0


def test_mastery_tracks_due_cards_and_lapses() -> None:
    state, _ = planned()
    card = state.cards(TENANT_A, OWNER_A)[0]
    review_card(state, TENANT_A, OWNER_A, card.id, 1)

    report = mastery(state, TENANT_A, OWNER_A)
    # mastery v1 reports an owner-level aggregate replicated onto every node, so
    # read one node rather than summing across them.
    assert {int(n["lapses"]) for n in report["nodes"]} == {1}
    assert {int(n["attempt_count"]) for n in report["nodes"]} == {0}


def test_learning_state_is_per_owner_and_per_tenant() -> None:
    state, _ = planned()
    seed(state, TENANT_B, OWNER_B)
    other = create_plan(
        state,
        TENANT_B,
        OWNER_B,
        exam_date=date.today() + timedelta(days=DAYS),
        hours_per_week=10,
        session_minutes=60,
    )

    a_cards = {c.id for c in state.cards(TENANT_A, OWNER_A)}
    b_cards = {c.id for c in state.cards(TENANT_B, OWNER_B)}
    assert a_cards and b_cards
    assert a_cards.isdisjoint(b_cards)
    assert other["plan_id"] != get_plan(state, TENANT_A, OWNER_A)["plan_id"]

    # A second owner inside tenant A gets their own empty schedule.
    assert state.cards(TENANT_A, OWNER_B) == []
    with pytest.raises(ValueError, match="onboarding required"):
        today(state, TENANT_A, OWNER_B)


def test_review_refuses_across_tenants() -> None:
    state, _ = planned()
    seed(state, TENANT_B, OWNER_B)
    create_plan(
        state,
        TENANT_B,
        OWNER_B,
        exam_date=date.today() + timedelta(days=DAYS),
        hours_per_week=10,
        session_minutes=60,
    )
    a_card = state.cards(TENANT_A, OWNER_A)[0]

    with pytest.raises(LookupError):
        review_card(state, TENANT_B, OWNER_B, a_card.id, 4)
