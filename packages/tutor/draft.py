"""Draft text from a tutor answer while it is being written (ADR 0025).

The tutor agents return one JSON object (``{"segments": [{"text": ...}, ...]}``).
While the transport streams, the partial JSON is read here and the ``text`` of
each segment is turned into small draft operations (append to segment *i*,
replace segment *i*, or shrink to *n* segments) for the browser.

Drafts are unvalidated, uncited model output. They are never persisted, never
logged, and the browser shows them only under a "draft, not yet checked" label
until the final judged answer replaces them; if the answer step fails they are
discarded. Grounding (``grounding``) and the semantic judge (``judge``) still
run on the validated output exactly as without streaming.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SEGMENTS = re.compile(r'"segments"\s*:\s*\[')
FLUSH_INTERVAL_S = 0.15


@dataclass(frozen=True, slots=True)
class DraftOp:
    """One draft change for a phase (``sources`` or ``web``)."""

    phase: str
    segment: int | None = None
    append: str | None = None
    text: str | None = None
    count: int | None = None

    def as_event(self) -> dict[str, Any]:
        event: dict[str, Any] = {"phase": self.phase}
        for key in ("segment", "append", "text", "count"):
            value = getattr(self, key)
            if value is not None:
                event[key] = value
        return event


DraftCallback = Callable[[DraftOp], None]


def _complete_escapes(raw: str) -> str:
    """Cut an unfinished escape sequence off the end of a partial JSON string body."""
    i = 0
    while i < len(raw):
        if raw[i] == "\\":
            need = 6 if raw[i + 1: i + 2] == "u" else 2
            if i + need > len(raw):
                return raw[:i]
            i += need
        else:
            i += 1
    return raw


def _decode(raw: str) -> str:
    try:
        value = json.loads('"' + _complete_escapes(raw) + '"')
    except ValueError:
        return ""
    return value if isinstance(value, str) else ""


def _read_string(buffer: str, start: int) -> tuple[str, int]:
    """Decode the JSON string opening at ``start``; partial strings decode their prefix."""
    i = start + 1
    while i < len(buffer):
        if buffer[i] == "\\":
            i += 2
            continue
        if buffer[i] == '"':
            return _decode(buffer[start + 1: i]), i + 1
        i += 1
    return _decode(buffer[start + 1:]), len(buffer)


def draft_texts(buffer: str) -> list[str]:
    """The ``text`` of every segment seen so far in a (partial) answer JSON."""
    match = SEGMENTS.search(buffer)
    if match is None:
        return []
    texts: list[str] = []
    depth, i = 0, match.end()
    key: str | None = None
    after_colon = False
    while i < len(buffer):
        char = buffer[i]
        if char == '"':
            value, i = _read_string(buffer, i)
            if depth == 1 and after_colon:
                if key == "text":
                    texts[-1] = value
                after_colon = False
            elif depth == 1:
                key = value
            continue
        if depth == 0 and char == "]":
            break
        if char in "{[":
            depth += 1
            if depth == 1:
                texts.append("")
                key, after_colon = None, False
        elif char in "}]":
            depth -= 1
        elif depth == 1 and char == ":":
            after_colon = True
        elif depth == 1 and char == ",":
            key, after_colon = None, False
        i += 1
    return texts


def diff_ops(phase: str, before: list[str], after: list[str]) -> list[DraftOp]:
    """The smallest append/replace/shrink operations that turn ``before`` into ``after``."""
    ops: list[DraftOp] = []
    if len(after) < len(before):
        ops.append(DraftOp(phase, count=len(after)))
    for index, text in enumerate(after):
        old = before[index] if index < len(before) else ""
        if text == old:
            continue
        if old and text.startswith(old):
            ops.append(DraftOp(phase, segment=index, append=text[len(old):]))
        else:
            ops.append(DraftOp(phase, segment=index, text=text))
    return ops


@dataclass(slots=True)
class DraftTracker:
    """Transport delta callback that emits throttled draft operations for one phase."""

    phase: str
    emit: DraftCallback
    interval: float = FLUSH_INTERVAL_S
    clock: Callable[[], float] = time.monotonic
    buffers: dict[int, list[str]] = field(default_factory=dict)
    active: int | None = None
    emitted: list[str] = field(default_factory=list)
    last_flush: float = 0.0

    def __call__(self, block: int, chunk: str) -> None:
        self.buffers.setdefault(block, []).append(chunk)
        if block != self.active and SEGMENTS.search("".join(self.buffers[block])):
            self.active = block
        if self.clock() - self.last_flush >= self.interval:
            self.flush()

    def flush(self) -> None:
        self.last_flush = self.clock()
        if self.active is None:
            return
        texts = draft_texts("".join(self.buffers[self.active]))
        for op in diff_ops(self.phase, self.emitted, texts):
            self.emit(op)
        self.emitted = texts
