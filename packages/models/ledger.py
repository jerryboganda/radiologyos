"""One record per model-call attempt, handed to registered recorders (ADR 0032).

The gateway builds a ``CallRecord`` for every target it tries — success,
failure, usage-limit pause, or quality-gate rejection — and passes it to each
recorder. Records hold ids, names, numbers, and an error class only: never a
prompt, an output, or any user text (hard rule 4). Recorders must not raise;
a failing recorder is logged once by class name and skipped, so recording can
never break a model call.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import UUID

from packages.observability import trace

log = logging.getLogger("radbrain.models.ledger")
Status = Literal["ok", "error", "usage_limit", "rejected"]


@dataclass(frozen=True, slots=True)
class CallRecord:
    agent: str  # "<name>/v<version>"
    route: str
    backend: str
    model: str
    effort: str
    status: Status
    duration_ms: int
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    request_id: str | None = None


Recorder = Callable[[CallRecord], None]
_recorders: list[Recorder] = []
_lock = threading.Lock()
_warned: set[str] = set()


def add_recorder(recorder: Recorder) -> None:
    with _lock:
        if recorder not in _recorders:
            _recorders.append(recorder)


def remove_recorder(recorder: Recorder) -> None:
    with _lock:
        if recorder in _recorders:
            _recorders.remove(recorder)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return None


def token_counts(usage: Mapping[str, Any] | None) -> tuple[int | None, int | None]:
    """(input, output) tokens from a transport's usage block, parsed defensively.

    Claude Code reports ``input_tokens`` plus cache creation/read tokens and
    ``output_tokens``; OpenAI-style APIs report ``prompt_tokens`` and
    ``completion_tokens``. Missing or malformed values give None.
    """
    if not isinstance(usage, Mapping):
        return None, None
    parts = [_int(usage.get(k)) for k in ("input_tokens", "cache_creation_input_tokens",
                                          "cache_read_input_tokens")]
    known = [p for p in parts if p is not None]
    prompt = sum(known) if known else _int(usage.get("prompt_tokens"))
    output = _int(usage.get("output_tokens"))
    if output is None:
        output = _int(usage.get("completion_tokens"))
    return prompt, output


def with_context(record: CallRecord) -> CallRecord:
    """Stamp the current request/task identity onto a record."""
    ctx = trace.current()
    return replace(record, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                   request_id=ctx.request_id)


def emit(record: CallRecord) -> None:
    stamped = with_context(record)
    with _lock:
        recorders = list(_recorders)
    for recorder in recorders:
        try:
            recorder(stamped)
        except Exception as exc:  # a recorder must never break a model call
            name = getattr(recorder, "__qualname__", type(recorder).__name__)
            if name not in _warned:
                _warned.add(name)
                log.warning("ledger_recorder_failed recorder=%s error=%s",
                            name, type(exc).__name__)
