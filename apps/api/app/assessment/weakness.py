"""Weakness-loop seam for assessment outcomes (gap G5).

When a viva or staged image case finishes, its weak and missed turns become
``WeakArea`` records and are handed to every registered sink inside the
owner's tenant transaction. A sink (for example the card-reset loop) is
registered once at import time with ``register_weakness_sink``; with no sink
registered the weak areas stay in the stored debrief only. A failing sink is
logged by id and never breaks the session. Records carry ids, the examiner's
question, and resolved citations, never the candidate's answer.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from packages.assessment.viva import weak_turns
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("radbrain.assessment")


@dataclass(frozen=True, slots=True)
class WeakArea:
    tenant_id: UUID
    user_id: UUID
    origin: str  # "viva" | "image_case"
    session_id: UUID
    turn_no: int
    topic: str
    prompt: str
    verdict: str
    stage: str | None
    citations: tuple[Mapping[str, Any], ...]


WeaknessSink = Callable[[AsyncSession, Sequence[WeakArea]], Awaitable[None]]
_SINKS: list[WeaknessSink] = []


def register_weakness_sink(sink: WeaknessSink) -> None:
    if sink not in _SINKS:
        _SINKS.append(sink)


def unregister_weakness_sink(sink: WeaknessSink) -> None:
    if sink in _SINKS:
        _SINKS.remove(sink)


def weak_areas(row: Mapping[str, Any], turns: Sequence[Mapping[str, Any]]) -> list[WeakArea]:
    """Missed or partial turns, with the citations of the points the candidate missed."""
    areas = []
    for turn in weak_turns(turns):
        evaluation = turn["evaluation"]
        cites: list[Mapping[str, Any]] = []
        for point in evaluation.get("points", []):
            if point.get("status") != "matched":
                cites.extend(point.get("citations") or [])
        teaching = evaluation.get("teaching_point") or {}
        cites.extend(teaching.get("citations") or [])
        areas.append(WeakArea(
            tenant_id=row["tenant_id"], user_id=row["user_id"], origin=row["kind"],
            session_id=row["id"], turn_no=int(turn["turn_no"]), topic=row.get("topic") or "",
            prompt=str(turn["prompt"]), verdict=str(evaluation.get("verdict")),
            stage=turn.get("stage"), citations=tuple(_unique(cites)),
        ))
    return areas


def _unique(cites: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    out = []
    for cite in cites:
        key = str(cite.get("chunk_id") or cite.get("figure_id") or cite.get("ref"))
        if key not in seen:
            seen.add(key)
            out.append(cite)
    return out


async def report_weak_areas(session: AsyncSession, areas: Sequence[WeakArea]) -> int:
    """Hand weak areas to every registered sink; returns how many sinks accepted them."""
    if not areas:
        return 0
    accepted = 0
    for sink in list(_SINKS):
        try:
            async with session.begin_nested():
                await sink(session, areas)
            accepted += 1
        except Exception:
            log.warning("weakness sink failed session=%s", areas[0].session_id)
    return accepted
