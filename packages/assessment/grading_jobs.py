"""State machine for asynchronous free-text exam grading (no database).

A job is keyed by (tenant, exam, question, ``GRADING_VERSION``) and moves
``pending -> running -> graded | failed``; a usage-limit pause or a transient
model error returns it to ``pending`` for a later run. ``claimable`` makes a
re-delivered or duplicated Celery task a no-op while another run holds the job,
and lets a run take over a job whose worker died mid-run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from packages.assessment import agents
from packages.assessment.grading import apply_seq_grade
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import Transport

GRADING_VERSION = 1
GRADER = "seq_grade/v1"
MAX_ERRORS = 3
MAX_RUNS = 48
STALE_AFTER = timedelta(minutes=15)
JobStatus = Literal["pending", "running", "graded", "failed"]
OutcomeKind = Literal["graded", "deferred", "retry", "failed"]


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    graded: dict[str, Any] | None = None
    error: str | None = None

    @property
    def status(self) -> JobStatus:
        if self.kind == "graded":
            return "graded"
        return "failed" if self.kind == "failed" else "pending"


def claimable(status: str, updated_at: datetime, now: datetime) -> bool:
    """May a run start? Pending always; running only once its worker looks dead."""
    if status == "pending":
        return True
    return status == "running" and now - updated_at >= STALE_AFTER


def run_grading(
    transport: Transport | None,
    question: Mapping[str, Any],
    answer_text: str,
    errors: int,
    runs: int,
) -> Outcome:
    """Grade one answer; ``errors``/``runs`` are the counts before this run."""
    if transport is None:
        return _pause(runs, "model_unavailable")
    try:
        grade = agents.grade_free_text(transport, question, answer_text)
    except UsageLimitError:
        return _pause(runs, "usage_limit")
    except ModelCallError:
        if errors + 1 >= MAX_ERRORS:
            return Outcome("failed", error="model_error")
        return Outcome("retry", error="model_error")
    scheme = question["answer"].get("marking_scheme", [])
    return Outcome("graded", graded=apply_seq_grade(scheme, grade))


def _pause(runs: int, code: str) -> Outcome:
    if runs + 1 >= MAX_RUNS:
        return Outcome("failed", error=f"{code}_exhausted")
    return Outcome("deferred", error=code)
