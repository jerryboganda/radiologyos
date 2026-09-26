"""Generate -> deterministic checks -> independent model check -> status.

Runs synchronously (call it from a thread): one ``question_generate`` call,
then one ``question_check`` call per item that passed the deterministic checks,
in parallel. Items failing deterministic checks (including any citation to an
excerpt that was not supplied) are rejected outright; items the checker fails
are kept as ``draft``; only checker-passed items become ``active``.

Chunk-based generation uses ``question_generate/v1``. Claim-based SBA generation
(ADR 0029) uses ``question_generate/v2`` over a topic's verified claims and adds
one deterministic check: enough distractors must name a supplied graph neighbour.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from packages.assessment import agents
from packages.assessment.claim_questions import (
    Neighbour,
    claim_problems,
    graph_distractors,
    render_neighbours,
)
from packages.assessment.models import GeneratedItem, QuestionCheck
from packages.assessment.validation import Excerpt, check_item, stored_parts
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import Transport

GENERATOR = "question_generate/v1"
CLAIM_GENERATOR = "question_generate/v2"
CHECKER = "question_check/v1"
MAX_PARALLEL_CHECKS = 4


@dataclass(slots=True)
class GenerationResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[int] = field(default_factory=list)  # generator index of each item


def _safe_check(
    transport: Transport, item: GeneratedItem, excerpts: Sequence[Excerpt]
) -> QuestionCheck | None:
    try:
        return agents.check(transport, item, excerpts)
    except UsageLimitError:
        raise
    except ModelCallError:
        return None


def to_row(
    item: GeneratedItem,
    verdict: QuestionCheck | None,
    excerpts: Sequence[Excerpt],
    exam_target: str,
    generator: str = GENERATOR,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    passed = verdict is not None and verdict.passed
    quality: dict[str, Any] = {
        **(extra or {}),
        "deterministic": "pass",
        "checker": CHECKER,
        "check": verdict.model_dump() if verdict is not None else {"error": "check_failed"},
        "passed": passed,
        "difficulty": item.difficulty,
        "cognitive_level": item.cognitive_level,
    }
    return {
        "type": item.type,
        "exam_tags": [exam_target],
        "topic": item.topic,
        "stem": item.stem,
        "explanation": item.explanation,
        "status": "active" if passed else "draft",
        "quality": quality,
        "agent_version": f"{generator}+{CHECKER}",
        **stored_parts(item, excerpts),
    }


def _screen(
    items: Sequence[GeneratedItem], item_type: str, excerpts: Sequence[Excerpt],
    neighbours: Sequence[Neighbour] | None,
) -> tuple[GenerationResult, list[GeneratedItem]]:
    supplied = [excerpt.ref for excerpt in excerpts]
    outcome = GenerationResult()
    candidates: list[GeneratedItem] = []
    for index, item in enumerate(items):
        problems = check_item(item, item_type, supplied)
        if neighbours is not None and not problems:
            problems = claim_problems(item, neighbours)
        if problems:
            outcome.rejected.append({"index": index, "reasons": problems})
        else:
            candidates.append(item)
            outcome.indexes.append(index)
    return outcome, candidates


def _checked(
    transport: Transport, candidates: Sequence[GeneratedItem], excerpts: Sequence[Excerpt]
) -> list[QuestionCheck | None]:
    if not candidates:
        return []
    workers = min(MAX_PARALLEL_CHECKS, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda it: _safe_check(transport, it, excerpts), candidates))


def generate_items(
    transport: Transport,
    excerpts: Sequence[Excerpt],
    item_type: str,
    exam_target: str,
    count: int,
    topic: str | None,
) -> GenerationResult:
    drafted = agents.generate(transport, excerpts, item_type, exam_target, count, topic)
    outcome, candidates = _screen(drafted.items[:count], item_type, excerpts, None)
    verdicts = _checked(transport, candidates, excerpts)
    outcome.items = [
        to_row(item, verdict, excerpts, exam_target)
        for item, verdict in zip(candidates, verdicts, strict=True)
    ]
    return outcome


def generate_claim_items(
    transport: Transport,
    excerpts: Sequence[Excerpt],
    neighbours: Sequence[Neighbour],
    exam_target: str,
    count: int,
    topic: str,
) -> GenerationResult:
    """SBA items from verified claims with graph-neighbour distractors (v2)."""
    drafted = agents.generate_from_claims(
        transport, excerpts, render_neighbours(neighbours), exam_target, count, topic)
    outcome, candidates = _screen(drafted.items[:count], "sba", excerpts, neighbours)
    verdicts = _checked(transport, candidates, excerpts)
    outcome.items = [
        to_row(item, verdict, excerpts, exam_target, CLAIM_GENERATOR,
               {"basis": "claims", "graph_distractors": graph_distractors(item, neighbours)})
        for item, verdict in zip(candidates, verdicts, strict=True)
    ]
    return outcome
