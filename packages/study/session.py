"""Today session runner: a durable, resumable sequence built from the day's plan.

Spec section 7 ("Daily session"): due cards -> learn (cited chunks and figures for
the top priority topic) -> a timed SBA block (60 % today's topics, the rest from
weak topics; open weakness re-tests first) -> one viva prompt. A step with nothing
to show is left out, so every step the runner shows has cited material behind it.
Selection is deterministic for a given seed. No model is called here.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

SESSION_VERSION = 1
MAX_REVIEW_CARDS = 60
REVIEW_CARDS_PER_MINUTE = 3
LEARN_MINUTES_PER_CHUNK = 5
MAX_LEARN_CHUNKS = 6
MAX_FIGURES = 4
SBA_MAX = 20
MINUTES_PER_SBA = 1.5
RETEST_SHARE = 0.4
TODAY_SHARE = 0.6
VIVA_MINUTES = 5

StepKind = Literal["review", "learn", "test", "viva"]
STEP_ORDER: tuple[StepKind, ...] = ("review", "learn", "test", "viva")


@dataclass(frozen=True, slots=True)
class SbaCandidate:
    """An active SBA question; ``code`` is its resolved curriculum node (None: unmapped)."""

    question_id: str
    code: str | None
    days_since_attempt: float | None = None


@dataclass(frozen=True, slots=True)
class Retest:
    """An open weakness event whose question should be re-tested."""

    event_id: str
    question_id: str


@dataclass(frozen=True, slots=True)
class VivaChoice:
    """A graded open question, or a self-review prompt built from a cited chunk."""

    mode: Literal["graded", "self_review"]
    question_id: str | None = None
    reference_chunk_id: str | None = None
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class SessionInputs:
    plan: Mapping[str, Any]
    card_ids: Sequence[str]
    topic: Mapping[str, str] | None
    chunk_ids: Sequence[str]
    figure_ids: Sequence[str]
    candidates: Sequence[SbaCandidate]
    retests: Sequence[Retest]
    viva: VivaChoice | None
    within: Callable[[str | None, str], bool] = field(
        default=lambda code, root: code == root)
    seed: int = 0


def plan_block(plan: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    return next((b for b in plan.get("blocks", []) if b.get("kind") == kind), None)


def focus_topic(plan: Mapping[str, Any]) -> dict[str, str] | None:
    """The learn block's first topic, else the plan's top priority."""
    learn = plan_block(plan, "learn")
    topics = list(learn.get("topics") or []) if learn else []
    first = topics[0] if topics else (plan.get("priorities") or [None])[0]
    if not first:
        return None
    return {"code": str(first["code"]), "title": str(first["title"])}


def focus_codes(plan: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(today's topic codes, weak topic codes) from the plan's test block."""
    test = plan_block(plan, "test")
    today = [str(c) for c in (test.get("topics") or [])] if test else []
    weak = [str(c) for c in (test.get("weak_topics") or [])] if test else []
    topic = focus_topic(plan)
    if not today and topic:
        today = [topic["code"]]
    return today, weak


def learn_chunk_limit(plan: Mapping[str, Any]) -> int:
    learn = plan_block(plan, "learn")
    minutes = int(learn["minutes"]) if learn else 0
    return max(min(minutes // LEARN_MINUTES_PER_CHUNK, MAX_LEARN_CHUNKS), 1)


def sba_count(plan: Mapping[str, Any]) -> int:
    test = plan_block(plan, "test")
    if test is None:
        return 0
    return max(min(int(test.get("questions") or 0), SBA_MAX), 1)


def _ordered(pool: list[SbaCandidate], rng: random.Random) -> list[SbaCandidate]:
    """Never-attempted first, then least recently attempted; ties in seeded order."""
    rng.shuffle(pool)
    return sorted(pool, key=lambda c: -(math.inf if c.days_since_attempt is None
                                          else c.days_since_attempt))


def _take(pool: Sequence[SbaCandidate], chosen: dict[str, None], limit: int) -> None:
    for candidate in pool:
        if len(chosen) >= limit:
            return
        chosen.setdefault(candidate.question_id, None)


def select_sba(inputs: SessionInputs, count: int) -> tuple[list[str], list[str]]:
    """Question ids for the SBA block and the weakness events they re-test."""
    if count <= 0 or not inputs.candidates:
        return [], []
    rng = random.Random(inputs.seed)  # nosec B311 - question order, not security
    active = {c.question_id for c in inputs.candidates}
    retests = [r for r in inputs.retests if r.question_id in active]
    chosen: dict[str, None] = {}
    events: list[str] = []
    for retest in retests:
        if len(chosen) >= math.ceil(count * RETEST_SHARE):
            break
        if retest.question_id not in chosen:
            chosen[retest.question_id] = None
        events.append(retest.event_id)
    today, weak = focus_codes(inputs.plan)
    matches = [c for c in inputs.candidates if any(inputs.within(c.code, r) for r in today)]
    weakest = [c for c in inputs.candidates if any(inputs.within(c.code, r) for r in weak)]
    room = count - len(chosen)
    _take(_ordered(matches, rng), chosen, len(chosen) + round(room * TODAY_SHARE))
    _take(_ordered(weakest, rng), chosen, count)
    _take(_ordered(list(inputs.candidates), rng), chosen, count)
    return list(chosen), events


def _review(inputs: SessionInputs) -> dict[str, Any] | None:
    ids = list(dict.fromkeys(inputs.card_ids))[:MAX_REVIEW_CARDS]
    if not ids:
        return None
    return {"kind": "review", "minutes": math.ceil(len(ids) / REVIEW_CARDS_PER_MINUTE),
            "payload": {"card_ids": ids}}


def _learn(inputs: SessionInputs) -> dict[str, Any] | None:
    if not inputs.chunk_ids or inputs.topic is None:
        return None
    learn = plan_block(inputs.plan, "learn")
    minutes = int(learn["minutes"]) if learn else LEARN_MINUTES_PER_CHUNK * len(inputs.chunk_ids)
    return {"kind": "learn", "minutes": minutes,
            "payload": {"topic": dict(inputs.topic),
                        "chunk_ids": list(inputs.chunk_ids)[:MAX_LEARN_CHUNKS],
                        "figure_ids": list(inputs.figure_ids)[:MAX_FIGURES]}}


def _test(inputs: SessionInputs) -> dict[str, Any] | None:
    ids, events = select_sba(inputs, sba_count(inputs.plan))
    if not ids:
        return None
    limit = max(math.ceil(len(ids) * MINUTES_PER_SBA), 1)
    today, _ = focus_codes(inputs.plan)
    return {"kind": "test", "minutes": limit,
            "payload": {"question_ids": ids, "retest_event_ids": events,
                        "time_limit_minutes": limit, "topics": today}}


def _viva(inputs: SessionInputs) -> dict[str, Any] | None:
    choice = inputs.viva
    if choice is None or (choice.question_id is None and choice.reference_chunk_id is None):
        return None
    block = plan_block(inputs.plan, "viva")
    return {"kind": "viva", "minutes": int(block["minutes"]) if block else VIVA_MINUTES,
            "payload": {"mode": choice.mode, "question_id": choice.question_id,
                        "reference_chunk_id": choice.reference_chunk_id,
                        "prompt": choice.prompt,
                        "topic": dict(inputs.topic) if inputs.topic else None}}


def build_steps(inputs: SessionInputs) -> list[dict[str, Any]]:
    """Numbered steps (1..n) in the fixed order; empty steps are left out."""
    built = [_review(inputs), _learn(inputs), _test(inputs), _viva(inputs)]
    steps = [step for step in built if step is not None]
    return [{**step, "step_no": index} for index, step in enumerate(steps, start=1)]


def self_review_prompt(topic_title: str) -> str:
    return (f"Viva: an examiner asks you about {topic_title}. Give the key imaging "
            "findings, the main differentials, and the next step, as you would aloud.")


def current_step(steps: Sequence[Mapping[str, Any]]) -> int | None:
    """The step to resume: the first one that is neither done nor skipped."""
    return next((int(s["step_no"]) for s in steps
                 if s["status"] not in ("done", "skipped")), None)


def step_minutes(step: Mapping[str, Any]) -> int:
    """Minutes spent on a finished step: wall time, capped at twice the plan plus 5."""
    started, finished = step.get("started_at"), step.get("completed_at")
    if started is None or finished is None or step.get("status") != "done":
        return 0
    elapsed = max((finished - started).total_seconds() / 60, 0.0)
    return int(round(min(elapsed, 2.0 * int(step.get("minutes") or 0) + 5)))


def summarize(
    steps: Sequence[Mapping[str, Any]], reviews: int, weighted_coverage: float
) -> dict[str, Any]:
    """The frozen completion summary; ``weighted_coverage`` feeds the pace projection."""
    test = next((s for s in steps if s["kind"] == "test"), None)
    answers = dict(((test or {}).get("result") or {}).get("answers") or {})
    viva = next((s for s in steps if s["kind"] == "viva"), None)
    return {
        "steps_done": sum(1 for s in steps if s["status"] == "done"),
        "steps_skipped": sum(1 for s in steps if s["status"] == "skipped"),
        "steps_total": len(steps),
        "reviews": reviews,
        "sba_answered": len(answers),
        "sba_correct": sum(1 for a in answers.values() if a.get("correct")),
        "viva_answered": bool(viva and (viva.get("result") or {}).get("answer_text")),
        "minutes": sum(step_minutes(s) for s in steps),
        "weighted_coverage": round(min(max(weighted_coverage, 0.0), 1.0), 4),
    }
