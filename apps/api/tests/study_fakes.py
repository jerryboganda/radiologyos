"""In-memory StudyRepo that mirrors the SQL repository's per-user semantics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4


class MemoryStudyRepo:
    def __init__(self) -> None:
        self.profiles: dict[UUID, dict[str, Any]] = {}
        self.plans: dict[tuple[UUID, date], dict[str, Any]] = {}
        self.chunks: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.cards: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.reviews: list[dict[str, Any]] = []
        self.weights: list[tuple[UUID, dict[str, Any]]] = []
        self.questions: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.attempts: list[dict[str, Any]] = []
        self.baselines: list[tuple[UUID, dict[str, Any]]] = []
        self.exams: dict[UUID, dict[str, Any]] = {}
        self.reports: dict[tuple[UUID, date], dict[str, Any]] = {}
        self.lapses: list[tuple[UUID, UUID, UUID]] = []
        self.commits = 0

    def add_question(self, owner: UUID, code: str | None, status: str = "active") -> UUID:
        """An SBA question whose cited chunk maps to ``code`` (None: unmapped)."""
        question_id = uuid4()
        self.questions[question_id] = (owner, {"id": question_id, "curriculum_code": code,
                                               "status": status, "type": "sba"})
        return question_id

    def add_attempt(self, owner: UUID, question_id: UUID, score: float, at: datetime) -> None:
        self.attempts.append({"user_id": owner, "question_id": question_id, "score": score,
                              "max_score": 1.0, "created_at": at})

    def add_chunk(self, owner: UUID, text: str = "Crazy paving on HRCT.",
                  heading: str = "PAP") -> UUID:
        chunk_id = uuid4()
        self.chunks[chunk_id] = (owner, {
            "id": chunk_id, "source_id": uuid4(), "source_title": "Synthetic chest",
            "page_from": 1, "page_to": 1, "heading": heading, "text": text,
            "block_refs": [{"page": 1, "block": 0}], "chunk_no": len(self.chunks)})
        return chunk_id

    async def commit(self) -> None:
        self.commits += 1

    async def release(self) -> None:
        self.commits += 1

    async def rebind(self) -> None:
        return None

    async def get_profile(self, user_id: UUID) -> dict[str, Any] | None:
        return self.profiles.get(user_id)

    async def save_profile(self, user_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        self.profiles[user_id] = {**data, "updated_at": datetime.now(UTC)}
        return self.profiles[user_id]

    async def delete_plans_from(self, user_id: UUID, day: date) -> None:
        for key in [k for k in self.plans if k[0] == user_id and k[1] >= day]:
            del self.plans[key]

    async def get_plan(self, user_id: UUID, day: date) -> dict[str, Any] | None:
        return self.plans.get((user_id, day))

    async def save_plan(self, user_id: UUID, plan: dict[str, Any]) -> datetime:
        generated = datetime.now(UTC)
        self.plans[(user_id, date.fromisoformat(plan["plan_date"]))] = {
            "plan_version": plan["plan_version"], "blocks": plan["blocks"],
            "detail": {k: v for k, v in plan.items() if k != "blocks"},
            "generated_at": generated}
        return generated

    async def chunk_for_user(self, user_id: UUID, chunk_id: UUID) -> dict[str, Any] | None:
        found = self.chunks.get(chunk_id)
        return found[1] if found and found[0] == user_id else None

    async def chunks_for_user(
        self, user_id: UUID, source_id: UUID | None, chunk_ids: Sequence[UUID], limit: int
    ) -> list[dict[str, Any]]:
        mine = [c for owner, c in self.chunks.values() if owner == user_id]
        if chunk_ids:
            return [c for c in mine if c["id"] in chunk_ids]
        carded = {c["source_chunk_id"] for _, c in self.cards.values()}
        return [c for c in mine if c["source_id"] == source_id and c["id"] not in carded][:limit]

    async def insert_card(self, user_id: UUID, card: dict[str, Any]) -> dict[str, Any]:
        row = {**card, "id": uuid4(), "state": "new", "stability": 0.0, "difficulty": 0.0,
               "last_review_at": None, "reps": 0, "lapses": 0, "created_at": card["due_at"]}
        self.cards[row["id"]] = (user_id, row)
        return row

    async def get_card(self, user_id: UUID, card_id: UUID) -> dict[str, Any] | None:
        found = self.cards.get(card_id)
        return found[1] if found and found[0] == user_id else None

    def _mine(self, user_id: UUID) -> list[dict[str, Any]]:
        return [c for owner, c in self.cards.values() if owner == user_id]

    async def due_cards(
        self, user_id: UUID, now: datetime, limit: int, new_limit: int
    ) -> list[dict[str, Any]]:
        due = sorted((c for c in self._mine(user_id) if c["state"] != "new"
                      and c["due_at"] <= now), key=lambda c: c["due_at"])[:limit]
        fresh = [c for c in self._mine(user_id) if c["state"] == "new"]
        return due + fresh[: max(min(new_limit, limit - len(due)), 0)]

    async def counts(self, user_id: UUID, now: datetime, day_start: datetime) -> dict[str, int]:
        cards = self._mine(user_id)
        reviews = [r for r in self.reviews if r["user_id"] == user_id]
        today = [r for r in reviews if r["reviewed_at"] >= day_start]
        return {
            "cards": len(cards),
            "due": sum(c["state"] != "new" and c["due_at"] <= now for c in cards),
            "new": sum(c["state"] == "new" for c in cards),
            "reviews": len(reviews), "reviews_today": len(today),
            "new_today": sum(r["state_before"] == "new" for r in today),
        }

    async def apply_review(
        self, user_id: UUID, card: dict[str, Any], review: dict[str, Any]
    ) -> dict[str, Any]:
        owner, row = self.cards[card["id"]]
        assert owner == user_id
        row.update(card)
        review_id = uuid4()
        self.reviews.append({**review, "id": review_id, "user_id": user_id,
                             "card_id": card["id"], "curriculum_code": row["curriculum_code"]})
        return {**row, "review_id": review_id}

    async def record_lapse(
        self, user_id: UUID, card: dict[str, Any], review_id: UUID, now: datetime
    ) -> None:
        self.lapses.append((user_id, card["id"], review_id))

    async def topic_cards(self, user_id: UUID) -> list[dict[str, Any]]:
        return self._mine(user_id)

    async def reviews_since(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        return [r for r in self.reviews if r["user_id"] == user_id and r["reviewed_at"] >= since]

    async def approved_weights(self, user_id: UUID) -> list[dict[str, Any]]:
        return [w for owner, w in self.weights if owner == user_id]

    def _mapped(self, user_id: UUID) -> dict[UUID, dict[str, Any]]:
        return {qid: q for qid, (owner, q) in self.questions.items()
                if owner == user_id and q["curriculum_code"] is not None}

    async def question_attempts(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        mapped = self._mapped(user_id)
        return [{**a, "curriculum_code": mapped[a["question_id"]]["curriculum_code"]}
                for a in self.attempts if a["user_id"] == user_id
                and a["question_id"] in mapped and a["created_at"] >= since]

    async def question_counts(self, user_id: UUID) -> list[dict[str, Any]]:
        attempted = {a["question_id"] for a in self.attempts if a["user_id"] == user_id}
        out: dict[str, dict[str, Any]] = {}
        for qid, q in self._mapped(user_id).items():
            row = out.setdefault(q["curriculum_code"], {"curriculum_code": q["curriculum_code"],
                                                        "questions": 0, "attempted": 0})
            if q["status"] == "active":
                row["questions"] += 1
                row["attempted"] += qid in attempted
        return list(out.values())

    async def baseline_candidates(self, user_id: UUID) -> list[dict[str, Any]]:
        return [{"question_id": qid, "curriculum_code": q["curriculum_code"]}
                for qid, q in self._mapped(user_id).items()
                if q["status"] == "active" and q["type"] == "sba"]

    async def latest_baseline(self, user_id: UUID) -> dict[str, Any] | None:
        mine = [b for owner, b in self.baselines if owner == user_id]
        if not mine:
            return None
        row = mine[-1]
        return {**row, "deadline_at": self.exams[row["exam_id"]]["deadline_at"]}

    async def create_baseline(
        self, user_id: UUID, systems: dict[str, str], minutes: int, now: datetime
    ) -> dict[str, Any]:
        exam_id = uuid4()
        self.exams[exam_id] = {"id": exam_id, "deadline_at": now + timedelta(minutes=minutes),
                               "submitted_at": None, "result": None, "minutes": minutes}
        row = {"id": uuid4(), "exam_id": exam_id, "question_ids": [UUID(q) for q in systems],
               "systems": dict(systems), "started_at": now, "submitted_at": None,
               "results": None}
        self.baselines.append((user_id, row))
        return {**row, "deadline_at": self.exams[exam_id]["deadline_at"]}

    async def baseline_exam(self, user_id: UUID, exam_id: UUID) -> dict[str, Any] | None:
        return self.exams.get(exam_id)

    async def finish_baseline(
        self, user_id: UUID, baseline_id: UUID, submitted_at: datetime,
        results: Sequence[dict[str, Any]],
    ) -> None:
        for owner, row in self.baselines:
            if owner == user_id and row["id"] == baseline_id:
                row.update(submitted_at=submitted_at, results=list(results))

    async def reviews_between(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        return [r for r in self.reviews
                if r["user_id"] == user_id and start <= r["reviewed_at"] < end]

    async def attempts_between(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        return [a for a in self.attempts
                if a["user_id"] == user_id and start <= a["created_at"] < end]

    async def save_report(
        self, user_id: UUID, week_start: date, version: int, report: dict[str, Any]
    ) -> datetime:
        generated = datetime.now(UTC)
        self.reports[(user_id, week_start)] = {"week_start": week_start, "report": report,
                                               "report_version": version,
                                               "generated_at": generated}
        return generated

    async def latest_report(self, user_id: UUID) -> dict[str, Any] | None:
        mine = sorted((k[1], v) for k, v in self.reports.items() if k[0] == user_id)
        return mine[-1][1] if mine else None
