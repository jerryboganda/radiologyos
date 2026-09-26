"""In-memory StudyRepo that mirrors the SQL repository's per-user semantics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4


class MemoryStudyRepo:
    def __init__(self) -> None:
        self.profiles: dict[UUID, dict[str, Any]] = {}
        self.plans: dict[tuple[UUID, date], dict[str, Any]] = {}
        self.chunks: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.cards: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.reviews: list[dict[str, Any]] = []
        self.commits = 0

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
        self.reviews.append({**review, "user_id": user_id, "card_id": card["id"],
                             "curriculum_code": row["curriculum_code"]})
        return row

    async def topic_cards(self, user_id: UUID) -> list[dict[str, Any]]:
        return self._mine(user_id)

    async def reviews_since(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        return [r for r in self.reviews if r["user_id"] == user_id and r["reviewed_at"] >= since]
