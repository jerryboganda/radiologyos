"""Knowledge API: concepts, cited claims, conflicts, topic weights, mappings, extraction."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from apps.api.app.knowledge import mappings, service, weights
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
ExamTarget = Literal["imm", "fcps2_theory", "fcps2_toacs", "frcr", "unknown"]
WeightTarget = Literal["imm", "fcps2_theory", "fcps2_toacs", "frcr", "unknown", "all"]


class ConceptSummary(BaseModel):
    id: UUID
    name: str
    aliases: list[str]
    concept_type: str
    curriculum_code: str | None
    claim_count: int
    open_conflicts: int


class ClaimOut(BaseModel):
    id: UUID
    claim_type: str
    statement: str
    evidence_span: str
    status: str
    verification: str
    importance: int
    modality: str
    citation: dict[str, Any]
    supporting: list[dict[str, Any]]
    agent_version: str


class EdgeOut(BaseModel):
    id: UUID
    relation: str
    direction: Literal["in", "out"]
    other_id: UUID
    other_name: str
    citation: dict[str, Any]


class ConflictSide(BaseModel):
    claim_id: UUID
    statement: str
    evidence_span: str
    citation: dict[str, Any]


class ConflictOut(BaseModel):
    id: UUID
    concept_id: UUID
    concept_name: str
    kind: str
    description: str
    status: str
    resolution: str | None
    preferred_claim: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    claim_a: ConflictSide
    claim_b: ConflictSide


class ConceptDetail(BaseModel):
    id: UUID
    name: str
    aliases: list[str]
    concept_type: str
    curriculum_code: str | None
    curriculum_confidence: float | None
    summary: str
    claims: list[ClaimOut]
    edges: list[EdgeOut]
    conflicts: list[ConflictOut]


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(min_length=1, max_length=2000)
    preferred_claim_id: UUID | None = None


class TopicWeightOut(BaseModel):
    id: UUID
    exam_target: str
    curriculum_code: str
    topic: str
    weight: float
    basis: dict[str, Any]
    approved: bool
    approved_at: datetime | None
    computed_at: datetime


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exam_target: WeightTarget
    weight_ids: list[UUID] | None = Field(default=None, max_length=500)


class ApproveResponse(BaseModel):
    exam_target: str
    approved: int


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["notes", "past_paper"] = "notes"
    exam_target: ExamTarget | None = None
    year: int | None = Field(default=None, ge=1990, le=2100)


class ExtractResponse(BaseModel):
    source_id: UUID
    job_id: UUID
    mode: str


class MappingOut(BaseModel):
    id: UUID
    source_id: UUID
    source_title: str
    page_from: int
    page_to: int
    curriculum_code: str
    topic: str
    confidence: float
    status: Literal["accepted", "review", "rejected"]
    agent_version: str
    created_at: datetime
    excerpt: str


class MappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject", "code"]
    curriculum_code: str | None = Field(default=None, min_length=1, max_length=60)


class CurriculumSystem(BaseModel):
    code: str
    title: str


def enqueue_knowledge(tenant_id: UUID, source_id: UUID, body: ExtractRequest) -> None:
    from apps.worker.app.celery_app import celery_app

    celery_app.send_task(
        "radbrain.knowledge_extract",
        args=[str(tenant_id), str(source_id), body.mode, body.exam_target, body.year],
    )


def _conflict(row: dict[str, Any]) -> ConflictOut:
    sides = {
        side: ConflictSide(claim_id=row[f"{side}_id"], statement=row[f"{side}_statement"],
                           evidence_span=row[f"{side}_span"], citation=row[f"{side}_citation"])
        for side in ("a", "b")
    }
    fields = {k: v for k, v in row.items() if k[:2] not in ("a_", "b_")}
    return ConflictOut(**fields, claim_a=sides["a"], claim_b=sides["b"])


@router.get("/concepts", response_model=list[ConceptSummary])
async def list_concepts(
    principal: PrincipalDep, session: SessionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ConceptSummary]:
    rows = await service.search_concepts(session, principal.user_id, q, limit)
    return [ConceptSummary(**row) for row in rows]


@router.get("/concepts/{concept_id}", response_model=ConceptDetail)
async def get_concept(
    concept_id: UUID, principal: PrincipalDep, session: SessionDep
) -> ConceptDetail:
    found = await service.concept_detail(session, principal.user_id, concept_id)
    if found is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return ConceptDetail(
        **{k: v for k, v in found.items() if k not in ("claims", "edges", "conflicts")},
        claims=[ClaimOut(**c) for c in found["claims"]],
        edges=[EdgeOut(**e) for e in found["edges"]],
        conflicts=[_conflict(c) for c in found["conflicts"]],
    )


@router.get("/conflicts", response_model=list[ConflictOut])
async def list_conflicts(
    principal: PrincipalDep, session: SessionDep,
    status_filter: Annotated[Literal["open", "resolved"] | None, Query(alias="status")] = "open",
) -> list[ConflictOut]:
    rows = await service.list_conflicts(session, principal.user_id, status_filter)
    return [_conflict(row) for row in rows]


@router.post("/conflicts/{conflict_id}/resolve", response_model=ConflictOut)
async def resolve_conflict(
    conflict_id: UUID, body: ResolveRequest, principal: PrincipalDep, session: SessionDep
) -> ConflictOut:
    try:
        row = await service.resolve_conflict(
            session, principal, conflict_id, body.resolution, body.preferred_claim_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    return _conflict(row)


@router.get("/topic-weights", response_model=list[TopicWeightOut])
async def list_topic_weights(
    principal: PrincipalDep, session: SessionDep,
    exam_target: Annotated[WeightTarget | None, Query()] = None,
) -> list[TopicWeightOut]:
    rows = await weights.list_weights(session, principal.user_id, exam_target)
    return [TopicWeightOut(**row) for row in rows]


@router.post("/topic-weights/approve", response_model=ApproveResponse)
async def approve_topic_weights(
    body: ApproveRequest, principal: PrincipalDep, session: SessionDep
) -> ApproveResponse:
    count = await weights.approve_weights(session, principal, body.exam_target, body.weight_ids)
    return ApproveResponse(exam_target=body.exam_target, approved=count)


@router.post(
    "/sources/{source_id}/extract",
    response_model=ExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def extract_source(
    source_id: UUID, principal: PrincipalDep, session: SessionDep,
    body: ExtractRequest | None = None,
) -> ExtractResponse:
    request = body or ExtractRequest()
    job_id = await weights.request_extraction(session, principal, source_id)
    if job_id is None:
        raise HTTPException(status_code=404, detail="source not found")
    enqueue_knowledge(principal.tenant_id, source_id, request)
    return ExtractResponse(source_id=source_id, job_id=job_id, mode=request.mode)


@router.get("/curriculum/systems", response_model=list[CurriculumSystem])
async def list_curriculum_systems(principal: PrincipalDep) -> list[CurriculumSystem]:
    return [CurriculumSystem(**row) for row in mappings.curriculum_systems()]


@router.get("/mappings", response_model=list[MappingOut])
async def list_mappings(
    principal: PrincipalDep, session: SessionDep,
    status_filter: Annotated[
        Literal["review", "accepted", "rejected"], Query(alias="status")
    ] = "review",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[MappingOut]:
    rows = await mappings.list_mappings(session, principal.user_id, status_filter, limit)
    return [MappingOut(**row) for row in rows]


@router.post("/mappings/{mapping_id}/decide", response_model=MappingOut)
async def decide_mapping(
    mapping_id: UUID, body: MappingDecision, principal: PrincipalDep, session: SessionDep
) -> MappingOut:
    """Accept, reject, or re-code one curriculum mapping (audited)."""
    if body.decision == "code" and not body.curriculum_code:
        raise HTTPException(status_code=422, detail="curriculum_code is required to re-code")
    try:
        row = await mappings.decide(
            session, principal, mapping_id, body.decision, body.curriculum_code
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="mapping not found")
    return MappingOut(**row)
