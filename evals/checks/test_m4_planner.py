"""M4 eval gate: exam-first onboarding, the daily planner, Today, and FSRS scheduling.

Covers slices P and Q of the A-Z queue against the DURABLE study code
(``apps/api/app/study``, ``apps/api/app/api/study.py`` and ``study_sessions.py``,
``packages/study``), driven over HTTP with in-memory repositories and a fixed
clock (see ``evals/checks/_m4_support.py``):

  P  the exam date comes first (409 until set); Today's block minutes sum to the
     day's budget; phase boundaries are exact and agree with days remaining; a
     past exam date is refused and a passed one clamps to taper; priorities are
     ordered and cover every weighted curriculum system; stale plans are rebuilt;
     no route ever claims a blueprint or a pass probability (CLAUDE.md "Never").
  Q  cards are cited and never duplicated by replanning; FSRS reviews move due
     dates, stability, and difficulty the right way; bad ratings answer 422; a
     review never edits the card a caller holds; foreign or unknown cards answer
     404; the due queue honours its limit; mastery is banded per system and
     tracks lapses; learning state is isolated per owner and per tenant.

Tenant isolation here is the repository boundary; the database RLS proofs for
these tables run in ``evals/checks/test_study_live.py``,
``test_study_depth_live.py`` and ``test_study_sessions_live.py``.

All content is synthetic.
"""

from __future__ import annotations

import asyncio
import dataclasses
from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.study import service
from apps.api.app.study.signals import curriculum_codes
from apps.api.tests.study_fakes import MemoryStudyRepo
from evals.checks._m4_support import (
    BANDS,
    NOW,
    OWNER_A,
    OWNER_B,
    TENANT_A,
    TENANT_B,
    Harness,
    Who,
    parse_time,
    probability_keys,
)
from packages.study import fsrs
from packages.study.mastery import band_for
from packages.study.planner import PLANNER_VERSION, phase_for


@pytest.fixture
def h() -> Harness:
    return Harness()


# ---------------------------------------------------------------- slice P


def test_today_requires_the_exam_date_first(h: Harness) -> None:
    for path in ("/v1/study/today", "/v1/study/progress", "/v1/study/sessions/today"):
        assert h.client.get(path).status_code == 409, path
    assert h.client.get("/v1/study/profile").status_code == 404
    profile = h.onboard(days=120)
    plan = h.today()
    assert plan["days_remaining"] == profile["days_remaining"] == 120
    assert plan["phase"] == profile["phase"] == "coverage_consolidation"
    assert plan["plan_version"] == PLANNER_VERSION
    kinds = [block["kind"] for block in plan["blocks"]]
    assert kinds == [k for k in ("review", "learn", "test", "viva") if k in kinds]


@pytest.mark.parametrize("minutes", [15, 20, 45, 60, 90, 241])
def test_today_block_minutes_sum_to_the_daily_budget(h: Harness, minutes: int) -> None:
    h.onboard(minutes=minutes)
    plan = h.today()
    assert plan["minutes"] == minutes
    assert sum(block["minutes"] for block in plan["blocks"]) == minutes
    assert all(block["minutes"] > 0 for block in plan["blocks"])


def test_the_session_runner_never_fakes_a_step_it_cannot_cite(h: Harness) -> None:
    """Replaces the preview's "omitted viva": empty steps are left out, never faked."""
    h.onboard()
    empty = h.client.get("/v1/study/sessions/today").json()
    assert empty["steps"] == []
    other_day = Harness()
    other_day.onboard()
    card = other_day.add_card()
    steps = other_day.client.get("/v1/study/sessions/today").json()["steps"]
    assert [step["kind"] for step in steps] == ["review"]
    shown = steps[0]["review"]["cards"]
    assert [c["id"] for c in shown] == [card["id"]] and shown[0]["citation"]


@pytest.mark.parametrize(
    ("days_remaining", "expected"),
    [(365, "coverage"), (181, "coverage"), (180, "coverage_consolidation"),
     (90, "coverage_consolidation"), (89, "consolidation"), (30, "consolidation"),
     (29, "exam_mode"), (7, "exam_mode"), (6, "taper"), (0, "taper")],
)
def test_phase_boundaries_are_exact(days_remaining: int, expected: str) -> None:
    assert phase_for(days_remaining) == expected


@pytest.mark.parametrize("days", [365, 181, 180, 90, 89, 30, 29, 7, 6, 1])
def test_plan_phase_agrees_with_its_own_days_remaining(h: Harness, days: int) -> None:
    profile = h.onboard(days=days)
    plan = h.today()
    assert plan["days_remaining"] == profile["days_remaining"] == days
    assert plan["phase"] == profile["phase"] == phase_for(days)
    assert h.progress()["phase"] == plan["phase"]
    assert plan["retention"] == (0.93 if days <= 30 else 0.90)


def test_a_past_exam_date_is_refused_and_a_passed_one_clamps(h: Harness) -> None:
    assert h.put_profile(days=-30).status_code == 422
    assert h.put_profile(days=0).status_code == 422
    assert h.client.get("/v1/study/today").status_code == 409
    h.onboard(days=3)
    Who.now = NOW + timedelta(days=10)  # the exam has since passed
    plan = h.today()
    assert plan["days_remaining"] == 0 and plan["phase"] == "taper"
    assert "learn" not in {block["kind"] for block in plan["blocks"]}
    assert h.progress()["days_remaining"] == 0


def test_planner_never_claims_a_blueprint_or_a_pass_probability(h: Harness) -> None:
    profile = h.onboard()
    plan = h.today()
    progress = h.progress()
    assert plan["weight_policy"] == progress["weight_policy"] == "equal_unvalidated"
    assert plan["weight_targets"] == []
    assert "No pass probability" in progress["notice"]
    session = h.client.get("/v1/study/sessions/today").json()
    for body in (profile, plan, progress, session):
        assert probability_keys(body) == []
        assert "pass_prob" not in str(body).lower()


def test_priorities_are_ordered_and_every_weighted_topic_is_represented(h: Harness) -> None:
    weights = {"CHEST": 0.5, "NEURO": 0.3, "GI": 0.2}
    h.approve_weights(OWNER_A, weights)
    h.onboard()
    plan = h.today()
    ranked = [(-item["priority"], item["code"]) for item in plan["priorities"]]
    assert ranked == sorted(ranked)
    assert len({item["code"] for item in plan["priorities"]}) == len(plan["priorities"])
    for item in plan["priorities"]:
        assert item["band"] in BANDS and item["band"] == band_for(item["mastery"])
    assert plan["weight_policy"] == "past_paper_approved"
    assert plan["priorities"][0]["code"] == "CHEST"  # heaviest, untouched, zero mastery
    topics = {t["code"]: t for t in h.progress()["topics"]}
    assert len(topics) == len(h.progress()["topics"])  # each system exactly once
    assert set(topics) == set(curriculum_codes())
    assert set(weights) <= {item["code"] for item in plan["priorities"]}
    assert sum(t["weight"] for t in topics.values()) == pytest.approx(1.0, abs=1e-4)
    assert topics["CHEST"]["weight"] > topics["NEURO"]["weight"] > topics["GI"]["weight"]


def test_replanning_rebuilds_stale_plans_and_keeps_the_exam_date(h: Harness) -> None:
    h.onboard(days=200)
    first = h.today()
    key = (OWNER_A, NOW.date())
    stale = {**h.repo.plans[key], "plan_version": PLANNER_VERSION - 1}
    stale["detail"] = {**stale["detail"], "marker": "stale"}
    h.repo.plans[key] = stale
    rebuilt = h.today()
    assert rebuilt["plan_version"] == PLANNER_VERSION
    assert "marker" not in h.repo.plans[key]["detail"]
    h.repo.plans[key]["detail"]["marker"] = "cached"
    assert h.today()["exam_date"] == first["exam_date"]
    assert h.repo.plans[key]["detail"].get("marker") == "cached"  # served from cache
    refreshed = h.today(refresh=True)
    assert "marker" not in h.repo.plans[key]["detail"]
    assert refreshed["exam_date"] == first["exam_date"]
    assert refreshed["minutes"] == first["minutes"]
    h.put_profile(days=200, minutes=90)  # a profile change clears today's plan
    assert h.today()["minutes"] == 90 and h.today()["exam_date"] == first["exam_date"]


# ---------------------------------------------------------------- slice Q


def test_cards_carry_citations_from_chunks_the_caller_owns(h: Harness) -> None:
    card = h.add_card()
    citation = card["citation"]
    assert citation["source_id"] and citation["chunk_id"]
    assert citation["page_from"] == 1 and citation["block_refs"] == [{"page": 1, "block": 0}]
    foreign = h.repo.add_chunk(OWNER_B)
    refused = h.client.post("/v1/study/cards", json={
        "chunk_id": str(foreign), "curriculum_code": "CHEST", "topic": "t",
        "front": "f", "back": "b"})
    assert refused.status_code == 404


def test_cards_are_not_duplicated_by_replanning(h: Harness) -> None:
    h.onboard()
    h.add_card()
    h.add_card(code="NEURO")
    before = len(h.repo.cards)
    h.today()
    h.today(refresh=True)
    h.put_profile(days=100)
    h.today()
    h.client.get("/v1/study/sessions/today")
    asyncio.run(service.plan_for_tomorrow(h.repo, OWNER_A, NOW))
    assert len(h.repo.cards) == before
    assert len({c["id"] for c in h.due(limit=200)}) == before


def test_a_good_review_pushes_the_card_into_the_future(h: Harness) -> None:
    h.onboard()
    card = h.add_card()
    body = h.review(card["id"], fsrs.Rating.GOOD).json()
    updated = body["card"]
    assert updated["reps"] == 1 and updated["state"] == "review"
    assert parse_time(updated["due_at"]) > NOW and body["scheduled_days"] >= 1
    assert updated["stability"] > card["stability"]


def test_a_lapse_shrinks_stability_and_schedules_a_ten_minute_retry(h: Harness) -> None:
    h.onboard()
    card = h.add_card()
    primed = h.review(card["id"], fsrs.Rating.EASY).json()["card"]
    Who.now = parse_time(primed["due_at"])
    body = h.review(card["id"], fsrs.Rating.AGAIN).json()
    lapsed = body["card"]
    assert lapsed["lapses"] == primed["lapses"] + 1 and lapsed["state"] == "relearning"
    assert lapsed["stability"] < primed["stability"]
    assert lapsed["difficulty"] > primed["difficulty"]
    assert parse_time(lapsed["due_at"]) - Who.now == timedelta(minutes=10)
    assert body["scheduled_days"] == 0


class _CopyingRepo(MemoryStudyRepo):
    """Hands out copies of stored cards, as the SQL repository does, and keeps them."""

    def __init__(self) -> None:
        super().__init__()
        self.held: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def get_card(self, user_id: UUID, card_id: UUID) -> dict[str, Any] | None:
        row = await super().get_card(user_id, card_id)
        if row is None:
            return None
        copy = dict(row)
        self.held.append((copy, deepcopy(copy)))
        return copy


def test_a_review_never_edits_the_card_a_caller_holds() -> None:
    repo = _CopyingRepo()
    chunk = repo.add_chunk(OWNER_A)
    fields = {"chunk_id": chunk, "curriculum_code": "CHEST", "topic": "t", "front": "f",
              "back": "b"}
    card = asyncio.run(service.create_card(repo, OWNER_A, fields, NOW))
    asyncio.run(service.review_card(repo, OWNER_A, card["id"], 1, NOW))
    asyncio.run(service.review_card(repo, OWNER_A, card["id"], 3, NOW + timedelta(hours=1)))
    assert len(repo.held) == 2
    for held, snapshot in repo.held:
        assert held == snapshot
    memory = fsrs.CardMemory()
    outcome = fsrs.review(memory, fsrs.Rating.GOOD, NOW)
    assert outcome.card is not memory and memory == fsrs.CardMemory()
    with pytest.raises(dataclasses.FrozenInstanceError):
        memory.reps = 5  # type: ignore[misc]


def test_higher_ratings_grow_stability_more(h: Harness) -> None:
    h.onboard()
    stabilities = []
    for rating in (fsrs.Rating.HARD, fsrs.Rating.GOOD, fsrs.Rating.EASY):
        card = h.add_card(front=f"Card rated {int(rating)}?")
        stabilities.append(h.review(card["id"], rating).json()["card"]["stability"])
    assert stabilities == sorted(stabilities) and len(set(stabilities)) == 3


@pytest.mark.parametrize("rating", [0, 5, -1, 99])
def test_out_of_range_ratings_are_rejected(h: Harness, rating: int) -> None:
    h.onboard()
    card = h.add_card()
    assert h.review(card["id"], rating).status_code == 422
    assert h.due()[0]["reps"] == 0 and h.repo.reviews == []


def test_review_refuses_a_card_owned_by_another_user(h: Harness) -> None:
    h.onboard()
    card = h.add_card()
    Who.act_as(OWNER_B, TENANT_A)
    assert h.review(card["id"], fsrs.Rating.GOOD).status_code == 404
    Who.act_as(OWNER_A, TENANT_A)
    assert h.due()[0]["reps"] == 0 and h.repo.reviews == []


def test_review_refuses_an_unknown_card(h: Harness) -> None:
    h.onboard()
    assert h.review(str(uuid4()), fsrs.Rating.GOOD).status_code == 404


def test_due_cards_respect_the_limit_and_drain_over_time(h: Harness) -> None:
    h.onboard()
    for index in range(5):
        h.add_card(front=f"Question {index}?")
    assert len(h.due(limit=2)) == 2
    assert len(h.due(limit=5)) == 5
    assert h.client.get("/v1/study/cards/due", params={"limit": 0}).status_code == 422
    for card in h.due(limit=5):
        h.review(card["id"], fsrs.Rating.GOOD)
    assert h.due(limit=5) == []
    Who.now = NOW + timedelta(days=30)
    assert len(h.due(limit=5)) == 5


def test_mastery_reports_a_banded_score_per_node(h: Harness) -> None:
    h.onboard()
    h.review(h.add_card()["id"], fsrs.Rating.GOOD)
    topics = h.progress()["topics"]
    assert {t["code"] for t in topics} == set(curriculum_codes())
    for topic in topics:
        for field in ("mastery", "accuracy", "coverage", "retrievability"):
            assert 0.0 <= topic[field] <= 1.0, (topic["code"], field)
        assert topic["band"] in BANDS and topic["band"] == band_for(topic["mastery"])
    chest = next(t for t in topics if t["code"] == "CHEST")
    assert chest["cards"] == 1 and chest["coverage"] == 1.0
    assert chest["mastery"] > max(t["mastery"] for t in topics if t["code"] != "CHEST")


def test_mastery_tracks_due_cards_and_lapses(h: Harness) -> None:
    h.onboard()
    card = h.add_card()
    h.add_card(code="NEURO")
    assert h.progress()["new_cards"] == 2 and h.progress()["due_now"] == 0
    primed = h.review(card["id"], fsrs.Rating.GOOD).json()["card"]
    Who.now = parse_time(primed["due_at"])
    assert h.progress()["due_now"] == 1
    h.review(card["id"], fsrs.Rating.AGAIN)
    lapses = {t["code"]: t["lapses"] for t in h.progress()["topics"]}
    assert lapses["CHEST"] == 1 and sum(lapses.values()) == 1  # per node, not replicated
    assert [lapse[1] for lapse in h.repo.lapses] == [UUID(card["id"])]
    assert h.progress()["reviews_total"] == 2


def test_learning_state_is_per_owner(h: Harness) -> None:
    h.onboard()
    card = h.add_card()
    Who.act_as(OWNER_B, TENANT_A)
    assert h.client.get("/v1/study/today").status_code == 409
    assert h.client.get("/v1/study/sessions/today").status_code == 409
    assert h.due() == []
    h.onboard()
    assert h.progress()["cards"] == 0
    assert h.review(card["id"], fsrs.Rating.GOOD).status_code == 404


def test_learning_state_is_per_tenant(h: Harness) -> None:
    h.onboard()
    a_card = h.add_card()
    Who.act_as(OWNER_B, TENANT_B)
    assert h.client.get("/v1/study/today").status_code == 409
    h.onboard()
    b_card = h.add_card()
    assert [c["id"] for c in h.due()] == [b_card["id"]]
    assert h.review(a_card["id"], fsrs.Rating.GOOD).status_code == 404
    assert h.repos[TENANT_A].cards.keys().isdisjoint(h.repos[TENANT_B].cards.keys())
    Who.act_as(OWNER_A, TENANT_A)
    assert [c["id"] for c in h.due()] == [a_card["id"]]
    assert h.review(b_card["id"], fsrs.Rating.GOOD).status_code == 404
