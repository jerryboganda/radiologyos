"""Cloze and image cards from the knowledge layer (ADR 0029).

``POST /v1/study/cards/from-knowledge`` turns the caller's verified claims into
cloze cards, or described figures into image cards, in plain code; the cards
join the ordinary FSRS review queue. Every card cites its claim evidence or its
figure; a candidate that cannot be cited is skipped (fail closed).
"""

from __future__ import annotations

from typing import Annotated, cast

from apps.api.app.api.study import NowDep, PrincipalDep, get_repo
from apps.api.app.schemas.study import KnowledgeCardsIn, KnowledgeCardsOut
from apps.api.app.study import knowledge_cards, service
from apps.api.app.study.ports import KnowledgeCardRepo
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/v1/study", tags=["study"])


def card_repo(repo: Annotated[service.StudyRepo, Depends(get_repo)]) -> KnowledgeCardRepo:
    return cast(KnowledgeCardRepo, repo)


RepoDep = Annotated[KnowledgeCardRepo, Depends(card_repo)]


@router.post("/cards/from-knowledge", response_model=KnowledgeCardsOut,
             status_code=status.HTTP_201_CREATED)
async def cards_from_knowledge(
    body: KnowledgeCardsIn, principal: PrincipalDep, repo: RepoDep, now: NowDep
) -> KnowledgeCardsOut:
    result = await knowledge_cards.generate(
        repo, principal.user_id, body.kind, body.source_id, body.topic, body.max_cards, now)
    return KnowledgeCardsOut.model_validate(result)
