"""Curriculum tree, node-id candidates, and the owner's approval of the pack (ADR 0023)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from apps.api.app.knowledge import curriculum_review
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal, require_roles
from fastapi import APIRouter, Depends, HTTPException, Query
from packages.curriculum.candidates import topic_candidates
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/knowledge/curriculum", tags=["knowledge"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]
SessionDep = Annotated[AsyncSession, Depends(tenant_db_session)]
APPROVER_ROLES = ("org_admin", "superadmin")
TargetFilter = Literal["fcps2_theory", "fcps2_toacs", "imm", "frcr", "frcr_2a", "frcr_2b"]


class CurriculumTreeNode(BaseModel):
    code: str
    title: str
    level: Literal["system", "topic", "subtopic"]
    exams: list[str]
    children: list[CurriculumTreeNode]


class CurriculumStatus(BaseModel):
    pack_id: str
    version: str
    pack_status: str
    content_hash: str
    source: str
    sources: list[str]
    counts: dict[str, int]
    review_status: Literal["pending", "approved", "rejected"]
    decided_at: datetime | None
    notes: str


class CurriculumOut(CurriculumStatus):
    systems: list[CurriculumTreeNode]


class CurriculumDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    notes: str = Field(default="", max_length=2000)


class CurriculumReviewOut(BaseModel):
    id: UUID
    pack_id: str
    pack_version: str
    content_hash: str
    decision: Literal["approved", "rejected"]
    notes: str
    decided_at: datetime


class NodeCandidate(BaseModel):
    id: str
    path: str
    label: str
    level: Literal["system", "topic", "subtopic"]


@router.get("", response_model=CurriculumOut)
async def get_curriculum(
    principal: PrincipalDep, session: SessionDep,
    exam_target: Annotated[TargetFilter | None, Query()] = None,
) -> CurriculumOut:
    state = await curriculum_review.status(session)
    systems = curriculum_review.tree(exam_target)
    return CurriculumOut(**state, systems=[CurriculumTreeNode(**s) for s in systems])


@router.get("/candidates", response_model=list[NodeCandidate])
async def list_candidates(
    principal: PrincipalDep,
    exam_target: Annotated[TargetFilter | None, Query()] = None,
    max_level: Annotated[Literal["system", "topic", "subtopic"], Query()] = "subtopic",
) -> list[NodeCandidate]:
    """Valid curriculum node ids (any depth) for re-coding a mapping or for prompts."""
    targets = [exam_target] if exam_target else None
    return [NodeCandidate(**c) for c in topic_candidates(targets, max_level)]


@router.get("/reviews", response_model=list[CurriculumReviewOut])
async def list_reviews(principal: PrincipalDep, session: SessionDep) -> list[CurriculumReviewOut]:
    return [CurriculumReviewOut(**r) for r in await curriculum_review.history(session)]


@router.post("/decision", response_model=CurriculumStatus)
async def decide_curriculum(
    body: CurriculumDecision, principal: PrincipalDep, session: SessionDep
) -> CurriculumStatus:
    """Approve or reject the pack version shown (owner/admin only; audited)."""
    require_roles(principal, *APPROVER_ROLES)
    try:
        state = await curriculum_review.decide(
            session, principal, body.decision, body.content_hash, body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CurriculumStatus(**state)
