"""Generate cited recall cards from the caller's chunks with the ``card_generate`` agent.

The agent sees only chunks the caller owns. Every returned card must cite one of
the supplied chunk ids, use a known curriculum code, and quote verbatim evidence
from that chunk; anything else is rejected before it reaches the database.
Only ids and counts are logged (hard rule 4).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.study.service import (
    Invalid,
    NotFound,
    StudyError,
    StudyRepo,
    card_from_chunk,
    curriculum_codes,
)
from packages.models.claude_code import ModelCallError, UsageLimitError
from packages.models.gateway import Transport, run_agent, user_prompt
from packages.study.card_models import CardBatch, GeneratedCard

AGENT = "card_generate"
MAX_CHUNKS = 8
CHUNK_CHARS = 4000
log = logging.getLogger("radbrain.study")


class GenerationUnavailable(StudyError):
    status_code = 503


class GenerationFailed(StudyError):
    status_code = 502


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def build_prompt(chunks: Sequence[dict[str, Any]], codes: Sequence[str], max_cards: int) -> str:
    payload = {
        "max_cards": max_cards,
        "curriculum_codes": sorted(codes),
        "chunks": [
            {"id": str(c["id"]), "heading": c["heading"],
             "pages": f"{c['page_from']}-{c['page_to']}", "text": c["text"][:CHUNK_CHARS]}
            for c in chunks
        ],
    }
    return user_prompt(AGENT, payload=json.dumps(payload, ensure_ascii=False))


def accept_cards(
    batch: CardBatch, chunks: dict[UUID, dict[str, Any]], codes: frozenset[str], max_cards: int
) -> tuple[list[GeneratedCard], int]:
    """Keep cards that cite a supplied chunk with verbatim evidence; count the rest."""
    accepted: list[GeneratedCard] = []
    for card in batch.cards:
        chunk = chunks.get(card.chunk_id)
        if chunk is None or card.curriculum_code not in codes:
            continue
        if _norm(card.evidence) not in _norm(str(chunk["text"])):
            continue
        accepted.append(card)
    kept = accepted[:max_cards]
    return kept, len(batch.cards) - len(kept)


async def _select_chunks(
    repo: StudyRepo, user_id: UUID, source_id: UUID | None, chunk_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    if not chunk_ids and source_id is None:
        raise Invalid("give a source_id or chunk_ids")
    wanted = list(dict.fromkeys(chunk_ids))[:MAX_CHUNKS]
    chunks = await repo.chunks_for_user(user_id, source_id, wanted, MAX_CHUNKS)
    if wanted and len(chunks) != len(wanted):
        raise NotFound("chunk not found")
    if not chunks:
        raise NotFound("no chunks without cards were found")
    return chunks


def _call_agent(transport: Transport, prompt: str) -> CardBatch:
    try:
        parsed, _ = run_agent(transport, AGENT, prompt)
    except UsageLimitError as exc:
        raise GenerationUnavailable("model usage limit reached; try later") from exc
    except ModelCallError as exc:
        raise GenerationFailed("card generation failed") from exc
    assert isinstance(parsed, CardBatch)
    return parsed


async def generate_cards(
    repo: StudyRepo,
    transport: Transport,
    user_id: UUID,
    source_id: UUID | None,
    chunk_ids: Sequence[UUID],
    max_cards: int,
    now: datetime,
) -> dict[str, Any]:
    chunks = await _select_chunks(repo, user_id, source_id, chunk_ids)
    codes = curriculum_codes()
    prompt = build_prompt(chunks, sorted(codes), max_cards)
    # Close the read transaction while the model works (it can take minutes).
    await repo.release()
    batch = await asyncio.to_thread(_call_agent, transport, prompt)
    await repo.rebind()
    by_id = {c["id"]: c for c in chunks}
    accepted, rejected = accept_cards(batch, by_id, codes, max_cards)
    created = []
    for card in accepted:
        fields = card.model_dump(include={"curriculum_code", "topic", "front", "back"})
        row = card_from_chunk(by_id[card.chunk_id], fields, "generated", now)
        created.append(await repo.insert_card(user_id, row))
    await repo.commit()
    log.info("cards_generated", extra={"user_id": str(user_id), "chunks": len(chunks),
                                        "created": len(created), "rejected": rejected})
    return {"created": created, "rejected": rejected, "chunks_used": len(chunks)}
