from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from apps.api.app.preview.records import (
    PreviewAttempt,
    PreviewAudit,
    PreviewBlock,
    PreviewCard,
    PreviewChunk,
    PreviewClaim,
    PreviewExam,
    PreviewFigure,
    PreviewJob,
    PreviewPage,
    PreviewQuestion,
    PreviewSource,
    PreviewStep,
)

__all__ = [
    "PreviewAttempt",
    "PreviewAudit",
    "PreviewBlock",
    "PreviewCard",
    "PreviewChunk",
    "PreviewClaim",
    "PreviewExam",
    "PreviewFigure",
    "PreviewJob",
    "PreviewPage",
    "PreviewQuestion",
    "PreviewSource",
    "PreviewState",
    "PreviewStep",
    "TenantState",
]


@dataclass
class TenantState:
    sources: dict[UUID, PreviewSource] = field(default_factory=dict)
    pages: dict[UUID, list[PreviewPage]] = field(default_factory=dict)
    blocks: dict[UUID, list[PreviewBlock]] = field(default_factory=dict)
    figures: dict[UUID, list[PreviewFigure]] = field(default_factory=dict)
    chunks: dict[UUID, list[PreviewChunk]] = field(default_factory=dict)
    jobs: dict[UUID, PreviewJob] = field(default_factory=dict)
    claims: list[PreviewClaim] = field(default_factory=list)
    concepts: list[dict[str, object]] = field(default_factory=list)
    conflicts: list[dict[str, object]] = field(default_factory=list)
    cards: dict[UUID, PreviewCard] = field(default_factory=dict)
    questions: list[PreviewQuestion] = field(default_factory=list)
    attempts: list[PreviewAttempt] = field(default_factory=list)
    exams: dict[UUID, PreviewExam] = field(default_factory=dict)
    plans: dict[tuple[UUID, UUID], dict[str, object]] = field(default_factory=dict)
    threads: dict[tuple[UUID, UUID], list[dict[str, object]]] = field(default_factory=dict)
    settings: dict[tuple[UUID, UUID], dict[str, object]] = field(default_factory=dict)
    billing: dict[UUID, dict[str, object]] = field(default_factory=dict)
    audit: list[PreviewAudit] = field(default_factory=list)
    idempotency: dict[str, UUID] = field(default_factory=dict)


class PreviewState:
    def __init__(self) -> None:
        self._tenants: dict[UUID, TenantState] = {}
        self._lock = RLock()

    def reset(self) -> None:
        with self._lock:
            self._tenants.clear()

    def tenant(self, tenant_id: UUID) -> TenantState:
        with self._lock:
            return self._tenants.setdefault(tenant_id, TenantState())

    def add_source(self, source: PreviewSource) -> None:
        with self._lock:
            self.tenant(source.tenant_id).sources[source.id] = source

    def source(self, tenant_id: UUID, source_id: UUID) -> PreviewSource | None:
        with self._lock:
            return self.tenant(tenant_id).sources.get(source_id)

    def sources(self, tenant_id: UUID) -> list[PreviewSource]:
        with self._lock:
            return [
                item for item in self.tenant(tenant_id).sources.values() if item.deleted_at is None
            ]

    def soft_delete_source(self, tenant_id: UUID, source_id: UUID, deleted_at: datetime) -> bool:
        """Delete a source and purge every artifact derived from it.

        Slice U requires delete to cover derived artifacts, not just the source
        row. Pages, blocks, figures, chunks, jobs, and extracted claims are all
        removed, and the idempotency binding is released so the caller can
        re-ingest under the same key instead of being handed a deleted source.
        """
        with self._lock:
            state = self.tenant(tenant_id)
            source = state.sources.get(source_id)
            if source is None or source.deleted_at is not None:
                return False
            state.sources[source_id] = replace(
                source, deleted_at=deleted_at, status="deleted"
            )
            state.pages.pop(source_id, None)
            state.blocks.pop(source_id, None)
            state.figures.pop(source_id, None)
            state.chunks.pop(source_id, None)
            for job_id in [
                job.id for job in state.jobs.values() if job.source_id == source_id
            ]:
                state.jobs.pop(job_id, None)
            state.claims = [
                claim for claim in state.claims if claim.source_id != source_id
            ]
            for key in [k for k, v in state.idempotency.items() if v == source_id]:
                del state.idempotency[key]
            return True

    def set_content(
        self,
        tenant_id: UUID,
        source_id: UUID,
        pages: list[PreviewPage],
        blocks: list[PreviewBlock],
        figures: list[PreviewFigure],
        chunks: list[PreviewChunk],
    ) -> None:
        with self._lock:
            state = self.tenant(tenant_id)
            state.pages[source_id] = pages
            state.blocks[source_id] = blocks
            state.figures[source_id] = figures
            state.chunks[source_id] = chunks

    def page(self, tenant_id: UUID, source_id: UUID, page_no: int) -> PreviewPage | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self.tenant(tenant_id).pages.get(source_id, [])
                    if item.page_no == page_no
                ),
                None,
            )

    def page_blocks(self, tenant_id: UUID, source_id: UUID, page_no: int) -> list[PreviewBlock]:
        with self._lock:
            return [
                item
                for item in self.tenant(tenant_id).blocks.get(source_id, [])
                if item.page_no == page_no
            ]

    def source_figures(self, tenant_id: UUID, source_id: UUID) -> list[PreviewFigure]:
        with self._lock:
            return list(self.tenant(tenant_id).figures.get(source_id, []))

    def source_chunks(self, tenant_id: UUID, source_id: UUID) -> list[PreviewChunk]:
        with self._lock:
            return list(self.tenant(tenant_id).chunks.get(source_id, []))

    def add_job(self, job: PreviewJob) -> None:
        with self._lock:
            self.tenant(job.tenant_id).jobs[job.id] = job

    def job(self, tenant_id: UUID, job_id: UUID) -> PreviewJob | None:
        with self._lock:
            return self.tenant(tenant_id).jobs.get(job_id)

    def jobs(self, tenant_id: UUID) -> list[PreviewJob]:
        with self._lock:
            return list(self.tenant(tenant_id).jobs.values())

    def claims(self, tenant_id: UUID) -> list[PreviewClaim]:
        with self._lock:
            return list(self.tenant(tenant_id).claims)

    def add_claim(self, claim: PreviewClaim) -> None:
        with self._lock:
            self.tenant(claim.tenant_id).claims.append(claim)

    def concepts_for(self, tenant_id: UUID) -> list[dict[str, object]]:
        with self._lock:
            return list(self.tenant(tenant_id).concepts)

    def conflicts_for(self, tenant_id: UUID) -> list[dict[str, object]]:
        with self._lock:
            return list(self.tenant(tenant_id).conflicts)

    def add_concept(self, concept: dict[str, object]) -> None:
        with self._lock:
            self.tenant(UUID(str(concept["tenant_id"]))).concepts.append(concept)

    def add_conflict(self, conflict: dict[str, object]) -> None:
        with self._lock:
            self.tenant(UUID(str(conflict["tenant_id"]))).conflicts.append(conflict)

    def resolve_conflict(self, tenant_id: UUID, conflict_id: UUID, resolution: str) -> bool:
        with self._lock:
            for conflict in self.tenant(tenant_id).conflicts:
                if UUID(str(conflict["id"])) == conflict_id:
                    conflict["status"] = "resolved"
                    conflict["resolution"] = resolution
                    return True
            return False

    def questions(self, tenant_id: UUID) -> list[PreviewQuestion]:
        with self._lock:
            return list(self.tenant(tenant_id).questions)

    def add_question(self, question: PreviewQuestion) -> None:
        with self._lock:
            self.tenant(question.tenant_id).questions.append(question)

    def cards(self, tenant_id: UUID, owner_id: UUID) -> list[PreviewCard]:
        with self._lock:
            return [
                card for card in self.tenant(tenant_id).cards.values() if card.owner_id == owner_id
            ]

    def add_card(self, card: PreviewCard) -> None:
        with self._lock:
            self.tenant(card.tenant_id).cards[card.id] = card

    def card(self, tenant_id: UUID, card_id: UUID) -> PreviewCard | None:
        with self._lock:
            return self.tenant(tenant_id).cards.get(card_id)

    def add_attempt(self, attempt: PreviewAttempt) -> None:
        with self._lock:
            self.tenant(attempt.tenant_id).attempts.append(attempt)

    def attempts(self, tenant_id: UUID, owner_id: UUID) -> list[PreviewAttempt]:
        with self._lock:
            return [item for item in self.tenant(tenant_id).attempts if item.owner_id == owner_id]

    def add_exam(self, exam: PreviewExam) -> None:
        with self._lock:
            self.tenant(exam.tenant_id).exams[exam.id] = exam

    def exam(self, tenant_id: UUID, exam_id: UUID) -> PreviewExam | None:
        with self._lock:
            return self.tenant(tenant_id).exams.get(exam_id)

    def plan(self, tenant_id: UUID, owner_id: UUID) -> dict[str, object] | None:
        with self._lock:
            return self.tenant(tenant_id).plans.get((tenant_id, owner_id))

    def set_plan(self, tenant_id: UUID, owner_id: UUID, plan: dict[str, object]) -> None:
        with self._lock:
            self.tenant(tenant_id).plans[(tenant_id, owner_id)] = plan

    def thread(self, tenant_id: UUID, owner_id: UUID) -> list[dict[str, object]]:
        with self._lock:
            return list(self.tenant(tenant_id).threads.get((tenant_id, owner_id), []))

    def set_thread(
        self,
        tenant_id: UUID,
        owner_id: UUID,
        messages: list[dict[str, object]],
    ) -> None:
        with self._lock:
            self.tenant(tenant_id).threads[(tenant_id, owner_id)] = messages

    def add_audit(self, event: PreviewAudit) -> None:
        with self._lock:
            self.tenant(event.tenant_id).audit.append(event)

    def audit(self, tenant_id: UUID) -> list[PreviewAudit]:
        with self._lock:
            return list(self.tenant(tenant_id).audit)

    def idempotent_source(self, tenant_id: UUID, key: str) -> UUID | None:
        with self._lock:
            return self.tenant(tenant_id).idempotency.get(key)

    def bind_idempotency(self, tenant_id: UUID, key: str, source_id: UUID) -> None:
        with self._lock:
            self.tenant(tenant_id).idempotency.setdefault(key, source_id)

    def new_id(self) -> UUID:
        return uuid4()

    def now(self) -> datetime:
        return datetime.now(UTC)
