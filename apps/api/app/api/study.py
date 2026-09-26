"""Study API: exam-first onboarding, daily plan, FSRS cards, reviews, progress.

The exam date comes first: every plan and progress route answers 409 until a
profile exists. No route returns a pass probability. The baseline diagnostic is
a server-timed assessment exam; the weekly report is written by a beat task.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.core.config import get_settings
from apps.api.app.core.time import now_utc
from apps.api.app.ops.ratelimit import rate_limit
from apps.api.app.schemas.study import (
    BaselineOut,
    CardIn,
    CardOut,
    GenerateIn,
    GenerateOut,
    PlanOut,
    ProfileIn,
    ProfileOut,
    ProgressOut,
    ReviewIn,
    ReviewOut,
    WeeklyReportOut,
)
from apps.api.app.security.context import (
    build_shared_dependencies,
    build_tenant_db_session_dependency,
)
from apps.api.app.security.principal import Principal
from apps.api.app.study import baseline, generate, reports, service
from apps.api.app.study.repo import SqlStudyRepo
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from packages.models.gateway import Transport
from packages.study.planner import phase_for
from sqlalchemy.ext.asyncio import AsyncSession

_, principal_context = build_shared_dependencies()
tenant_db_session = build_tenant_db_session_dependency(principal_context)
router = APIRouter(prefix="/v1/study", tags=["study"])

PrincipalDep = Annotated[Principal, Depends(principal_context)]


def get_repo(
    session: Annotated[AsyncSession, Depends(tenant_db_session)],
    principal: PrincipalDep,
) -> service.StudyRepo:
    return SqlStudyRepo(session, principal.tenant_id)


def get_now() -> datetime:
    return now_utc()


def get_transport() -> Transport:
    from packages.models.claude_code import ClaudeCodeTransport

    transport = ClaudeCodeTransport(get_settings().claude_code_bin)
    if not transport.available():
        raise HTTPException(status_code=503, detail="card generation is unavailable")
    return transport


RepoDep = Annotated[service.StudyRepo, Depends(get_repo)]
NowDep = Annotated[datetime, Depends(get_now)]


def _fail(exc: service.StudyError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _profile_out(profile: dict[str, Any], now: datetime) -> ProfileOut:
    remaining = service.days_remaining(profile, now)
    return ProfileOut(**{k: v for k, v in profile.items() if k != "updated_at"},
                      days_remaining=remaining, phase=phase_for(remaining))


@router.put("/profile", response_model=ProfileOut)
async def put_profile(
    body: ProfileIn, principal: PrincipalDep, repo: RepoDep, now: NowDep
) -> ProfileOut:
    data = body.model_dump(mode="python")
    try:
        profile = await service.save_profile(repo, principal.user_id, data, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return _profile_out(profile, now)


@router.get("/profile", response_model=ProfileOut)
async def get_profile(principal: PrincipalDep, repo: RepoDep, now: NowDep) -> ProfileOut:
    profile = await repo.get_profile(principal.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="set your exam date first")
    return _profile_out(profile, now)


@router.get("/today", response_model=PlanOut)
async def today(
    principal: PrincipalDep, repo: RepoDep, now: NowDep,
    refresh: Annotated[bool, Query()] = False,
) -> PlanOut:
    try:
        plan = await service.today_plan(repo, principal.user_id, now, refresh)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return PlanOut.model_validate(plan)


@router.post("/cards", response_model=CardOut, status_code=status.HTTP_201_CREATED)
async def create_card(
    body: CardIn, principal: PrincipalDep, repo: RepoDep, now: NowDep
) -> CardOut:
    try:
        row = await service.create_card(repo, principal.user_id, body.model_dump(), now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return CardOut.model_validate(row)


@router.get("/cards/due", response_model=list[CardOut])
async def due_cards(
    principal: PrincipalDep, repo: RepoDep, now: NowDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CardOut]:
    rows = await service.due_cards(repo, principal.user_id, now, limit)
    return [CardOut.model_validate(row) for row in rows]


@router.post("/cards/generate", response_model=GenerateOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("generate", principal_context))])
async def generate_cards(
    body: GenerateIn, principal: PrincipalDep, repo: RepoDep, now: NowDep,
    transport: Annotated[Transport, Depends(get_transport)],
) -> GenerateOut:
    try:
        result = await generate.generate_cards(
            repo, transport, principal.user_id, body.source_id, body.chunk_ids,
            body.max_cards, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return GenerateOut.model_validate(result)


@router.post("/cards/{card_id}/review", response_model=ReviewOut)
async def review_card(
    card_id: UUID, body: ReviewIn, principal: PrincipalDep, repo: RepoDep, now: NowDep
) -> ReviewOut:
    try:
        result = await service.review_card(repo, principal.user_id, card_id, body.rating, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return ReviewOut.model_validate(result)


@router.get("/progress", response_model=ProgressOut)
async def progress(principal: PrincipalDep, repo: RepoDep, now: NowDep) -> ProgressOut:
    try:
        result = await service.progress(repo, principal.user_id, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return ProgressOut.model_validate(result)


@router.post("/baseline", response_model=BaselineOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "An open baseline already exists"},
                        409: {"description": "Too few checked SBA questions"}})
async def start_baseline(
    principal: PrincipalDep, repo: RepoDep, now: NowDep, response: Response
) -> BaselineOut:
    """Build (or return the open) short SBA baseline across curriculum systems."""
    try:
        view, created = await baseline.start(
            repo, principal.user_id, now, seed=int(now.timestamp()))
    except service.StudyError as exc:
        raise _fail(exc) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return BaselineOut.model_validate(view)


@router.get("/baseline", response_model=BaselineOut)
async def get_baseline(principal: PrincipalDep, repo: RepoDep, now: NowDep) -> BaselineOut:
    try:
        view = await baseline.latest(repo, principal.user_id, now)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return BaselineOut.model_validate(view)


@router.get("/reports/latest", response_model=WeeklyReportOut)
async def latest_report(principal: PrincipalDep, repo: RepoDep) -> WeeklyReportOut:
    try:
        report = await reports.latest_report(repo, principal.user_id)
    except service.StudyError as exc:
        raise _fail(exc) from exc
    return WeeklyReportOut.model_validate(report)
