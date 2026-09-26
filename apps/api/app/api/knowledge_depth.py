"""Knowledge depth API: cited concept notes, graph, figures, trust, merges (ADR 0030)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.app.api.knowledge import ConflictOut, _conflict
from apps.api.app.knowledge import graph_view, merge_review, merges, notes, trust
from apps.api.app.library.service import audit
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
MergeStatus = Literal["review", "applied", "distinct", "undone"]


class ConceptNoteOut(BaseModel):
    id: UUID
    version: int
    status: Literal["draft", "verified", "superseded"]
    body: dict[str, Any]
    sentences: int
    dropped: int
    agent_version: str
    verified_at: datetime | None
    created_at: datetime


class NoteStateOut(BaseModel):
    concept_id: UUID
    state: Literal["missing", "current", "stale"]
    open_conflicts: int
    verifiable: bool
    note: ConceptNoteOut | None


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note_id: UUID


class SynthesizeResponse(BaseModel):
    concept_id: UUID
    queued: bool


class GraphNode(BaseModel):
    id: UUID
    name: str
    concept_type: str
    depth: int


class GraphEdge(BaseModel):
    source: UUID
    target: UUID
    relation: str


class GraphOut(BaseModel):
    center: UUID
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RelatedFigure(BaseModel):
    figure_id: UUID
    source_id: UUID
    source_title: str
    page_no: int
    caption: str
    description: str
    modality: str
    anatomy: str
    image_path: str | None


class TrustRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trust: Literal["a", "b", "both"]
    note: str = Field(default="", max_length=1000)


class MergeOut(BaseModel):
    id: UUID
    concept_a: UUID
    a_name: str
    concept_b: UUID
    b_name: str
    similarity: float
    decision: str
    confidence: float
    rationale: str
    status: MergeStatus
    survivor: UUID | None
    merged: UUID | None
    moved_claims: int
    agent_version: str
    created_at: datetime
    applied_at: datetime | None
    undone_at: datetime | None


class MergeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["merge", "distinct"]


def enqueue_note(tenant_id: UUID, user_id: UUID, concept_id: UUID) -> None:
    from apps.worker.app.celery_app import celery_app

    celery_app.send_task("radbrain.concept_note",
                         args=[str(tenant_id), str(user_id), str(concept_id)])


@router.get("/concepts/{concept_id}/note", response_model=NoteStateOut)
async def get_note(concept_id: UUID, principal: PrincipalDep,
                   session: SessionDep) -> NoteStateOut:
    found = await notes.note_state(session, principal.user_id, concept_id)
    if found is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return NoteStateOut(**found)


@router.post("/concepts/{concept_id}/note/synthesize", response_model=SynthesizeResponse,
             status_code=status.HTTP_202_ACCEPTED)
async def synthesize_note(concept_id: UUID, principal: PrincipalDep,
                          session: SessionDep) -> SynthesizeResponse:
    """Queue the Synthesis agent for the caller's note (a no-op if claims are unchanged)."""
    live = await notes.visible_concept(session, principal.user_id, concept_id)
    if live is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await audit(session, principal, "knowledge.note_requested", "concept", str(live))
    await session.commit()
    enqueue_note(principal.tenant_id, principal.user_id, live)
    return SynthesizeResponse(concept_id=live, queued=True)


@router.post("/concepts/{concept_id}/note/verify", response_model=NoteStateOut)
async def verify_note(concept_id: UUID, body: VerifyRequest, principal: PrincipalDep,
                      session: SessionDep) -> NoteStateOut:
    try:
        found = await notes.verify_note(session, principal, concept_id, body.note_id)
    except notes.NoteNotVerifiable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return NoteStateOut(**found)


@router.get("/concepts/{concept_id}/graph", response_model=GraphOut)
async def concept_graph(concept_id: UUID, principal: PrincipalDep, session: SessionDep,
                        depth: Annotated[int, Query(ge=1, le=2)] = 2) -> GraphOut:
    live = await notes.visible_concept(session, principal.user_id, concept_id)
    if live is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return GraphOut(**await graph_view.neighbourhood(session, principal.user_id, live, depth))


@router.get("/concepts/{concept_id}/figures", response_model=list[RelatedFigure])
async def concept_figures(concept_id: UUID, principal: PrincipalDep,
                          session: SessionDep) -> list[RelatedFigure]:
    live = await notes.visible_concept(session, principal.user_id, concept_id)
    if live is None:
        raise HTTPException(status_code=404, detail="concept not found")
    rows = await notes.related_figures(session, principal.user_id, live)
    return [RelatedFigure(figure_id=f["id"], image_path=f"/v1/library/figures/{f['id']}/image",
                          **{k: f[k] for k in ("source_id", "source_title", "page_no",
                                               "caption", "description", "modality",
                                               "anatomy")}) for f in rows]


@router.post("/conflicts/{conflict_id}/trust", response_model=ConflictOut)
async def trust_conflict(conflict_id: UUID, body: TrustRequest, principal: PrincipalDep,
                         session: SessionDep) -> ConflictOut:
    """Trust source A, source B, or keep both as valid in context (audited)."""
    try:
        row = await trust.trust_conflict(session, principal, conflict_id, body.trust, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    return _conflict(row)


@router.get("/merges", response_model=list[MergeOut])
async def list_merges(
    principal: PrincipalDep, session: SessionDep,
    status_filter: Annotated[MergeStatus | None, Query(alias="status")] = "review",
) -> list[MergeOut]:
    rows = await merge_review.list_merges(session, principal.user_id, status_filter)
    return [MergeOut(**row) for row in rows]


@router.post("/merges/{merge_id}/decide", response_model=MergeOut)
async def decide_merge(merge_id: UUID, body: MergeDecision, principal: PrincipalDep,
                       session: SessionDep) -> MergeOut:
    try:
        row = await merge_review.decide(session, principal, merge_id, body.decision)
    except merges.MergeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="merge decision not found")
    return MergeOut(**row)


@router.post("/merges/{merge_id}/undo", response_model=MergeOut)
async def undo_merge(merge_id: UUID, principal: PrincipalDep, session: SessionDep) -> MergeOut:
    """Reverse an applied merge: claims, edges, conflicts and aliases go back (audited)."""
    try:
        row = await merge_review.undo(session, principal, merge_id)
    except merges.MergeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="merge decision not found")
    return MergeOut(**row)
