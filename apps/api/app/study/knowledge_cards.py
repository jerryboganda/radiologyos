"""Make cloze cards from verified claims and image cards from figures (ADR 0029).

No model call: candidates are the caller's own usable claims or described
figures without a card yet; ``packages.study.knowledge_cards`` builds each card
and its citation, and a candidate without a blankable term or a resolvable
citation is skipped. Only ids and counts are logged (hard rule 4).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from apps.api.app.study.ports import KnowledgeCardRepo
from apps.api.app.study.signals import curriculum_codes
from packages.study.knowledge_cards import cloze_card, image_card

CANDIDATE_FACTOR = 3
log = logging.getLogger("radbrain.study")


async def generate(
    repo: KnowledgeCardRepo, user_id: UUID, kind: Literal["cloze", "image"],
    source_id: UUID | None, topic: str | None, max_cards: int, now: datetime,
) -> dict[str, Any]:
    systems = curriculum_codes()
    limit = max_cards * CANDIDATE_FACTOR
    if kind == "cloze":
        rows = await repo.cloze_candidates(user_id, source_id, topic, limit)
    else:
        rows = await repo.figure_candidates(user_id, source_id, topic, limit)
    created: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if len(created) >= max_cards:
            break
        card = cloze_card(row, systems) if kind == "cloze" else image_card(row, systems)
        stored = None if card is None else await repo.insert_knowledge_card(
            user_id, {**card, "due_at": now})
        if stored is None:
            skipped += 1
        else:
            created.append(stored)
    await repo.commit()
    log.info("knowledge_cards", extra={"user_id": str(user_id), "kind": kind,
                                       "created": len(created), "skipped": skipped})
    return {"kind": kind, "created": created, "skipped": skipped, "considered": len(rows)}
