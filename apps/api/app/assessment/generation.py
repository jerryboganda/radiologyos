"""Generate -> deterministic checks -> independent model check -> status.

Runs synchronously (call it from a thread): one ``question_generate`` call,
then one ``question_check`` call per item that passed the deterministic checks,
in parallel. Items failing deterministic checks (including any citation to an
excerpt that was not supplied) are rejected outright; items the checker fails
are kept as ``draft``; only checker-passed items become ``active``.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from packages.assessment import agents
from packages.assessment.models import GeneratedItem, QuestionCheck
from packages.assessment.validation import Excerpt, check_item, stored_parts
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import Transport

GENERATOR = "question_generate/v1"
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
) -> dict[str, Any]:
    passed = verdict is not None and verdict.passed
    quality: dict[str, Any] = {
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
        "agent_version": f"{GENERATOR}+{CHECKER}",
        **stored_parts(item, excerpts),
    }


def generate_items(
    transport: Transport,
    excerpts: Sequence[Excerpt],
    item_type: str,
    exam_target: str,
    count: int,
    topic: str | None,
) -> GenerationResult:
    drafted = agents.generate(transport, excerpts, item_type, exam_target, count, topic)
    supplied = [excerpt.ref for excerpt in excerpts]
    outcome = GenerationResult()
    candidates: list[GeneratedItem] = []
    for index, item in enumerate(drafted.items[:count]):
        problems = check_item(item, item_type, supplied)
        if problems:
            outcome.rejected.append({"index": index, "reasons": problems})
        else:
            candidates.append(item)
            outcome.indexes.append(index)
    if not candidates:
        return outcome
    workers = min(MAX_PARALLEL_CHECKS, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verdicts = list(pool.map(lambda it: _safe_check(transport, it, excerpts), candidates))
    outcome.items = [
        to_row(item, verdict, excerpts, exam_target)
        for item, verdict in zip(candidates, verdicts, strict=True)
    ]
    return outcome
