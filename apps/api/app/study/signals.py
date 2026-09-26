"""Per-system planner signals: approved weights, blended accuracy, coverage.

Mastery ``m = 0.5a + 0.3r + 0.2k`` per curriculum system (``packages.study``):
``a`` blends graded question attempts with card reviews, ``r`` is the mean FSRS
retrievability of the system's cards, and ``k`` is the share of its cards and
active questions touched at least once. Weights ``w`` come from the owner's
approved past-paper weights for their exam targets, else equal weights.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID

from apps.api.app.study.ports import StudyRepo
from packages.curriculum.contracts import CurriculumNode
from packages.curriculum.loader import radiology_pack
from packages.study import fsrs
from packages.study.mastery import (
    Mastery,
    coverage_share,
    mastery,
    question_attempt,
    review_attempt,
)
from packages.study.planner import TopicSignal
from packages.study.weights import ApprovedWeight, WeightMap, map_weights

ACCURACY_WINDOW = timedelta(days=90)
LAPSE_WINDOW_DAYS = 7


@lru_cache(maxsize=1)
def curriculum_systems() -> tuple[CurriculumNode, ...]:
    return tuple(node for node in radiology_pack().nodes if node.level == "system")


@lru_cache(maxsize=1)
def curriculum_nodes() -> tuple[CurriculumNode, ...]:
    """Every node of the pack, any depth (section, system, topic, subtopic ...)."""
    return tuple(radiology_pack().nodes)


def curriculum_codes() -> frozenset[str]:
    return frozenset(node.code for node in curriculum_systems())


@dataclass(frozen=True, slots=True)
class TopicRow:
    node: CurriculumNode
    mastery: Mastery
    signal: TopicSignal
    cards: int
    lapses: int
    weight: float
    questions: int = 0
    attempts: int = 0


@dataclass(slots=True)
class SystemData:
    cards: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    questions: int = 0
    attempted: int = 0


def _age(now: datetime, at: datetime) -> float:
    return (now - at).total_seconds() / 86400


def topic_row(node: CurriculumNode, data: SystemData, weight: float, now: datetime) -> TopicRow:
    memories = [fsrs.CardMemory(state=c["state"], stability=float(c["stability"]),
                                last_review_at=c["last_review_at"]) for c in data.cards]
    rs = [fsrs.current_retrievability(m, now) for m in memories]
    reviewed = sum(1 for mem in memories if mem.last_review_at is not None)
    accuracy = [review_attempt(_age(now, r["reviewed_at"]), int(r["rating"]))
                for r in data.reviews]
    accuracy += [question_attempt(_age(now, a["created_at"]), a["score"], a["max_score"])
                 for a in data.attempts]
    k = coverage_share(len(data.cards), reviewed, data.questions, data.attempted)
    m = mastery(accuracy, rs, k)
    touched = [mem.last_review_at for mem in memories if mem.last_review_at is not None]
    touched += [a["created_at"] for a in data.attempts]
    untouched = (now - max(touched)).days if touched else None
    lapse = any(int(r["rating"]) == 1 and _age(now, r["reviewed_at"]) <= LAPSE_WINDOW_DAYS
                for r in data.reviews)
    signal = TopicSignal(node.code, node.title, m.score, weight, lapse, False, untouched)
    return TopicRow(node, m, signal, len(data.cards), sum(int(c["lapses"]) for c in data.cards),
                    weight, data.questions, len(data.attempts))


async def load_weights(
    repo: StudyRepo, user_id: UUID, profile: dict[str, Any] | None
) -> WeightMap:
    rows = [ApprovedWeight(r["exam_target"], r["curriculum_code"], float(r["weight"]))
            for r in await repo.approved_weights(user_id)]
    targets = list(profile["exam_targets"]) if profile else []
    return map_weights(rows, targets, [node.code for node in curriculum_systems()])


async def _system_data(repo: StudyRepo, user_id: UUID, now: datetime) -> dict[str, SystemData]:
    data: dict[str, SystemData] = defaultdict(SystemData)
    since = now - ACCURACY_WINDOW
    for card in await repo.topic_cards(user_id):
        data[card["curriculum_code"]].cards.append(card)
    for review in await repo.reviews_since(user_id, since):
        data[review["curriculum_code"]].reviews.append(review)
    for attempt in await repo.question_attempts(user_id, since):
        data[attempt["curriculum_code"]].attempts.append(attempt)
    for count in await repo.question_counts(user_id):
        entry = data[count["curriculum_code"]]
        entry.questions, entry.attempted = int(count["questions"]), int(count["attempted"])
    return data


async def topic_rows(
    repo: StudyRepo, user_id: UUID, now: datetime, profile: dict[str, Any] | None = None
) -> tuple[list[TopicRow], WeightMap]:
    """One row per curriculum system, plus the weight basis in use."""
    weights = await load_weights(repo, user_id, profile)
    data = await _system_data(repo, user_id, now)
    rows = [topic_row(node, data[node.code], weights.weight_for(node.code), now)
            for node in curriculum_systems()]
    return rows, weights
