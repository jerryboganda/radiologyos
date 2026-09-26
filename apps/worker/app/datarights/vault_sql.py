"""Load one user's vault rows (ADR 0018, ADR 0031).

Runs inside the tenant's RLS transaction and is further scoped to sources the
user uploaded and has not deleted, so a vault never carries another member's or
another tenant's knowledge. Concepts are included only when they back at least
one of the user's cited claims.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from apps.worker.app.datarights.vault import (
    VaultCard,
    VaultClaim,
    VaultConcept,
    VaultEdge,
    VaultRows,
    VaultSource,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LIVE_SOURCES = "SELECT id FROM sources WHERE uploaded_by = :u AND deleted_at IS NULL"

SOURCES_SQL = text(
    "SELECT id, title FROM sources WHERE uploaded_by = :u AND deleted_at IS NULL"
)
CLAIMS_SQL = text(
    "SELECT id, concept_id, statement, evidence_span, status, source_id, page_from, page_to, "
    "citation->'blocks' AS blocks "
    f"FROM claims WHERE source_id IN ({LIVE_SOURCES})"  # nosec B608 - constant subquery
)
CONCEPTS_SQL = text(
    "SELECT id, name, concept_type, aliases, curriculum_code FROM concepts "
    f"WHERE id IN (SELECT concept_id FROM claims WHERE source_id IN ({LIVE_SOURCES}))"  # nosec B608
)
EDGES_SQL = text(
    "SELECT from_concept, to_concept, relation FROM concept_edges "
    f"WHERE source_id IN ({LIVE_SOURCES})"  # nosec B608 - constant subquery
)
CARDS_SQL = text(
    "SELECT id, curriculum_code, topic, front, back, source_id, "
    "citation->>'page_from' AS page_from, citation->>'page_to' AS page_to "
    "FROM cards WHERE user_id = :u"
)


def _blocks(value: Any) -> tuple[tuple[int, int], ...]:
    """(page_no, block_no) pairs from a claim citation's ``blocks`` array."""
    refs: list[tuple[int, int]] = []
    if isinstance(value, str):  # a driver without a jsonb codec returns text
        value = json.loads(value)
    for ref in value if isinstance(value, list) else []:
        page, block = _int((ref or {}).get("page_no")), _int((ref or {}).get("block_no"))
        if page is not None and block is not None:
            refs.append((page, block))
    return tuple(refs)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _rows(session: AsyncSession, statement: Any, user_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(statement, {"u": user_id})
    return [dict(row) for row in result.mappings()]


async def load_vault(session: AsyncSession, user_id: UUID) -> VaultRows:
    sources = [VaultSource(r["id"], str(r["title"] or ""))
               for r in await _rows(session, SOURCES_SQL, user_id)]
    concepts = [VaultConcept(r["id"], str(r["name"]), str(r["concept_type"] or "other"),
                             tuple(str(a) for a in (r["aliases"] or ())), r["curriculum_code"])
                for r in await _rows(session, CONCEPTS_SQL, user_id)]
    claims = [VaultClaim(r["id"], r["concept_id"], str(r["statement"]),
                         str(r["evidence_span"]), str(r["status"]), r["source_id"],
                         int(r["page_from"]), int(r["page_to"]), _blocks(r["blocks"]))
              for r in await _rows(session, CLAIMS_SQL, user_id)]
    edges = [VaultEdge(r["from_concept"], r["to_concept"], str(r["relation"]))
             for r in await _rows(session, EDGES_SQL, user_id)]
    cards = [VaultCard(r["id"], str(r["curriculum_code"]), str(r["topic"] or ""),
                       str(r["front"]), str(r["back"]), r["source_id"],
                       _int(r["page_from"]), _int(r["page_to"]))
             for r in await _rows(session, CARDS_SQL, user_id)]
    return VaultRows(sources, concepts, claims, edges, cards)
