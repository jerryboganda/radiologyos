"""The owner's red review list (owner rule, ADR 0038).

Everything whose final answer fell short of the quality bar (no stronger model
was left), or that every model failed, plus facts the extractor flagged as
contradicting standard teaching. Shown in red with a danger sign until the
owner has looked at it.

* ``GET  /v1/library/red-list``                    - both lists, newest first.
* ``POST /v1/library/red-list/{id}/reviewed``      - the owner has checked an item.
* ``POST /v1/library/red-list/claims/{id}``        - keep a flagged fact, or reject it.

Only the caller's own sources. Ids, titles, page numbers, and fixed reason
codes; a flagged fact's own statement and evidence are the owner's content.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/library/red-list", tags=["library"])
PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
LIMIT = 500
KIND = {"page_parse": "page", "image_case": "figure", "knowledge_extract": "notes"}
ITEMS = text(
    """
    SELECT e.id, e.source_id, s.title AS source_title, e.agent, e.unit, e.reason, e.created_at
    FROM model_escalations e JOIN sources s ON s.id = e.source_id AND s.tenant_id = e.tenant_id
    WHERE e.status = 'review' AND s.uploaded_by = :u AND s.deleted_at IS NULL
    ORDER BY e.created_at DESC LIMIT :n
    """
)
CLAIMS = text(
    """
    SELECT c.id, c.statement, c.doubt, c.evidence_span, c.source_id, s.title AS source_title,
           c.page_from, c.page_to
    FROM claims c JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
    WHERE c.status = 'flagged' AND s.uploaded_by = :u AND s.deleted_at IS NULL
    ORDER BY c.created_at DESC LIMIT :n
    """
)
CHUNK_PAGES = text(
    "SELECT text, page_from, page_to FROM chunks WHERE source_id = ANY(:ids)"
)


class RedItem(BaseModel):
    id: UUID
    source_id: UUID
    source_title: str
    kind: Literal["page", "figure", "notes"]
    page_from: int | None
    page_to: int | None
    reason: str
    created_at: datetime


class FlaggedFact(BaseModel):
    id: UUID
    statement: str
    doubt: str | None
    evidence_span: str
    source_id: UUID
    source_title: str
    page_from: int
    page_to: int


class RedList(BaseModel):
    items: list[RedItem]
    flagged_facts: list[FlaggedFact]


class Decision(BaseModel):
    decision: Literal["keep", "reject"]


def _hash(value: str) -> str:
    """The knowledge unit key (``apps.worker.app.knowledge.db.unit_hash``)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def _chunk_pages(session: AsyncSession, rows: list[Any]) -> dict[str, tuple[int, int]]:
    ids = list({r["source_id"] for r in rows if r["unit"].startswith("chunk:")})
    if not ids:
        return {}
    chunks = await session.execute(CHUNK_PAGES, {"ids": ids})
    return {f"chunk:{_hash(c.text)}": (c.page_from, c.page_to) for c in chunks}


def _pages(unit: str, chunks: dict[str, tuple[int, int]]) -> tuple[int | None, int | None]:
    if unit.startswith("page:") and unit[5:].isdigit():
        return int(unit[5:]), int(unit[5:])
    return chunks.get(unit, (None, None))


@router.get("", response_model=RedList)
async def red_list(principal: PrincipalDep, session: SessionDep) -> RedList:
    params = {"u": principal.user_id, "n": LIMIT}
    rows = [dict(r) for r in (await session.execute(ITEMS, params)).mappings()]
    chunks = await _chunk_pages(session, rows)
    items = [RedItem(id=r["id"], source_id=r["source_id"], source_title=r["source_title"],
                     kind=KIND.get(r["agent"], "notes"),
                     page_from=_pages(r["unit"], chunks)[0], page_to=_pages(r["unit"], chunks)[1],
                     reason=r["reason"], created_at=r["created_at"]) for r in rows]
    facts = [FlaggedFact(**dict(r)) for r in (await session.execute(CLAIMS, params)).mappings()]
    return RedList(items=items, flagged_facts=facts)


@router.post("/{item_id}/reviewed", status_code=204)
async def mark_reviewed(item_id: UUID, principal: PrincipalDep, session: SessionDep) -> Response:
    done = await session.execute(text(
        "UPDATE model_escalations e SET status = 'reviewed', resolved_at = now() "
        "FROM sources s WHERE e.id = :id AND e.status = 'review' AND s.id = e.source_id "
        "AND s.uploaded_by = :u AND s.deleted_at IS NULL"), {"id": item_id, "u": principal.user_id})
    if not getattr(done, "rowcount", 0):
        raise HTTPException(status_code=404, detail="not on your red list")
    return Response(status_code=204)


@router.post("/claims/{claim_id}", status_code=204)
async def decide_fact(
    claim_id: UUID, body: Decision, principal: PrincipalDep, session: SessionDep
) -> Response:
    """Keep the flagged fact as your source states it, or reject it."""
    status = "active" if body.decision == "keep" else "rejected"
    done = await session.execute(text(
        "UPDATE claims c SET status = :st, updated_at = now() FROM sources s "
        "WHERE c.id = :id AND c.status = 'flagged' AND s.id = c.source_id "
        "AND s.uploaded_by = :u AND s.deleted_at IS NULL"),
        {"st": status, "id": claim_id, "u": principal.user_id})
    if not getattr(done, "rowcount", 0):
        raise HTTPException(status_code=404, detail="not a flagged fact of yours")
    return Response(status_code=204)
