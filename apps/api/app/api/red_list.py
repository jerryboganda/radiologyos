"""The owner's red review list (owner rule, ADR 0038; verdicts and evidence, ADR 0041).

Everything whose final answer fell short of the quality bar (no stronger model
was left), or that every model failed, plus facts the extractor flagged as
contradicting standard teaching. Shown in red with a danger sign until the
owner has judged it; the owner's verdict and note are kept for the follow-up.

* ``GET  /v1/library/red-list/summary``        - per file: what is open, what is reviewed.
* ``GET  /v1/library/red-list``                - items and facts with their evidence
  (``status`` open|reviewed, optional ``source_id`` and ``kind``).
* ``GET  /v1/library/red-list/export.csv``     - everything, for review offline.
* ``POST /v1/library/red-list/{id}/verdict``   - correct | needs_fix | remove, and a note.
* ``POST /v1/library/red-list/{id}/reviewed``  - looked at, no verdict (kept for old clients).
* ``POST /v1/library/red-list/claims/{id}``    - keep or reject a flagged fact, and a note.

Only the caller's own sources. The evidence is the owner's own content, shown to
the owner; nothing here is logged. Every write commits: ``tenant_session`` never
does, so an uncommitted route returns a 204 that means nothing was saved.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from apps.api.app.library import red_review
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/library/red-list", tags=["library"])
PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
LIMIT = 2000
Status = Literal["open", "reviewed"]
Kind = Literal["page", "figure", "notes"]
Verdict = Literal["correct", "needs_fix", "remove"]


class Statement(BaseModel):
    statement: str
    evidence_span: str
    status: str


class FigureDetail(BaseModel):
    id: UUID
    figure_no: int | None
    caption: str | None
    description: str | None
    modality: str | None
    anatomy: str | None
    findings: list[str]
    source_quote: str | None
    impression_origin: str | None
    has_image: bool


class RedItem(BaseModel):
    id: UUID
    source_id: UUID
    source_title: str
    file_name: str
    kind: Kind
    page_from: int | None = None
    page_to: int | None = None
    reason: str
    status: Literal["review", "reviewed"]
    verdict: Verdict | None = None
    note: str | None = None
    created_at: datetime
    page_status: str | None = None
    own_text: str | None = None
    reading: str | None = None
    figures: list[FigureDetail] = []
    section_heading: str | None = None
    section_text: str | None = None
    statements: list[Statement] = []


class FlaggedFact(BaseModel):
    id: UUID
    statement: str
    doubt: str | None
    evidence_span: str
    source_id: UUID
    source_title: str
    file_name: str
    page_from: int
    page_to: int
    status: str
    note: str | None = None
    decided_at: datetime | None = None
    section_heading: str | None = None
    section_text: str | None = None


class RedList(BaseModel):
    items: list[RedItem]
    flagged_facts: list[FlaggedFact]


class FileSummary(BaseModel):
    source_id: UUID
    source_title: str
    file_name: str
    open_pages: int
    open_figures: int
    open_notes: int
    open_facts: int
    reviewed: int
    reasons: dict[str, int]


class VerdictBody(BaseModel):
    verdict: Verdict
    note: str | None = Field(default=None, max_length=4000)


class Decision(BaseModel):
    decision: Literal["keep", "reject"]
    note: str | None = Field(default=None, max_length=4000)


@router.get("/summary", response_model=list[FileSummary])
async def red_summary(principal: PrincipalDep, session: SessionDep) -> list[FileSummary]:
    return [FileSummary(**f) for f in await red_review.summary(session, principal.user_id)]


@router.get("", response_model=RedList)
async def red_list(
    principal: PrincipalDep, session: SessionDep, status: Status = "open",
    source_id: UUID | None = None, kind: Kind | None = None,
    limit: Annotated[int, Query(ge=1, le=LIMIT)] = 500,
) -> RedList:
    rows = await red_review.items(session, principal.user_id, status, source_id, kind, limit)
    facts = [] if kind else await red_review.facts(session, principal.user_id, status,
                                                   source_id, limit)
    return RedList(items=[_item(r) for r in rows], flagged_facts=[_fact(f) for f in facts])


def _item(r: dict[str, object]) -> RedItem:
    return RedItem.model_validate({**r, "verdict": r.get("owner_verdict"),
                                   "note": r.get("owner_note")})


def _fact(f: dict[str, object]) -> FlaggedFact:
    return FlaggedFact.model_validate({**f, "note": f.get("owner_note"),
                                       "decided_at": f.get("owner_decided_at")})


@router.get("/export.csv")
async def export_csv(principal: PrincipalDep, session: SessionDep) -> Response:
    """Every open and reviewed entry with its evidence, one row each."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["type", "file", "title", "pages", "problem", "status", "your verdict",
                "your note", "evidence"])
    for status in ("open", "reviewed"):
        for r in await red_review.items(session, principal.user_id, status, None, None, 10_000):
            w.writerow([r["kind"], r["file_name"], r["source_title"], _pages(r), r["reason"],
                        r["status"], r.get("owner_verdict") or "", r.get("owner_note") or "",
                        _evidence(r)])
        for f in await red_review.facts(session, principal.user_id, status, None, 10_000):
            w.writerow(["flagged fact", f["file_name"], f["source_title"], _pages(f),
                        f["doubt"] or "", f["status"], "", f.get("owner_note") or "",
                        f"{f['statement']} | evidence: {f['evidence_span']}"])
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "content-disposition": 'attachment; filename="red-review-list.csv"',
        "cache-control": "private, no-store"})


def _pages(r: dict[str, object]) -> str:
    a, b = r.get("page_from"), r.get("page_to")
    return "" if a is None else f"{a}" if b in (None, a) else f"{a}-{b}"


def _evidence(r: dict[str, object]) -> str:
    if r["kind"] == "figure":
        figs = r.get("figures")
        if not isinstance(figs, list):
            return ""
        return " || ".join(f"{f.get('description') or ''} | quote: {f.get('source_quote') or ''}"
                           for f in figs if isinstance(f, dict))
    return str(r.get("section_text") or r.get("reading") or r.get("own_text") or "")[:3000]


@router.post("/{item_id}/verdict", status_code=204)
async def give_verdict(
    item_id: UUID, body: VerdictBody, principal: PrincipalDep, session: SessionDep
) -> Response:
    done = await session.execute(text(
        "UPDATE model_escalations e SET status = 'reviewed', resolved_at = now(), "
        "owner_verdict = :v, owner_note = :note FROM sources s "
        "WHERE e.id = :id AND e.status IN ('review', 'reviewed') AND s.id = e.source_id "
        "AND s.uploaded_by = :u AND s.deleted_at IS NULL"),
        {"id": item_id, "u": principal.user_id, "v": body.verdict,
         "note": (body.note or "").strip() or None})
    if not getattr(done, "rowcount", 0):
        raise HTTPException(status_code=404, detail="not on your red list")
    await session.commit()  # the tenant session never commits; a 204 must mean saved
    return Response(status_code=204)


@router.post("/{item_id}/reviewed", status_code=204)
async def mark_reviewed(item_id: UUID, principal: PrincipalDep, session: SessionDep) -> Response:
    done = await session.execute(text(
        "UPDATE model_escalations e SET status = 'reviewed', resolved_at = now() "
        "FROM sources s WHERE e.id = :id AND e.status = 'review' AND s.id = e.source_id "
        "AND s.uploaded_by = :u AND s.deleted_at IS NULL"), {"id": item_id, "u": principal.user_id})
    if not getattr(done, "rowcount", 0):
        raise HTTPException(status_code=404, detail="not on your red list")
    await session.commit()  # see give_verdict: a 204 must mean saved
    return Response(status_code=204)


@router.post("/claims/{claim_id}", status_code=204)
async def decide_fact(
    claim_id: UUID, body: Decision, principal: PrincipalDep, session: SessionDep
) -> Response:
    """Keep the flagged fact as your source states it, or reject it (a later
    decision on the same fact replaces the earlier one)."""
    status = "active" if body.decision == "keep" else "rejected"
    done = await session.execute(text(
        "UPDATE claims c SET status = :st, updated_at = now(), owner_decided_at = now(), "
        "owner_note = :note FROM sources s WHERE c.id = :id "
        "AND (c.status = 'flagged' OR c.owner_decided_at IS NOT NULL) AND s.id = c.source_id "
        "AND s.uploaded_by = :u AND s.deleted_at IS NULL"),
        {"st": status, "id": claim_id, "u": principal.user_id,
         "note": (body.note or "").strip() or None})
    if not getattr(done, "rowcount", 0):
        raise HTTPException(status_code=404, detail="not a flagged fact of yours")
    await session.commit()  # see give_verdict: a 204 must mean saved
    return Response(status_code=204)
