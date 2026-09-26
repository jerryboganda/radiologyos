"""In-memory SessionRepo mirroring the SQL semantics of sessions, weakness and insights."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from apps.api.tests.study_fakes import MemoryStudyRepo
from packages.study import weakness


def _option(text: str) -> dict[str, Any]:
    return {"text": text, "explanation": f"Why {text}.",
            "citations": [{"ref": "E1", "kind": "chunk"}]}


class MemorySessionRepo(MemoryStudyRepo):
    def __init__(self) -> None:
        super().__init__()
        self.sessions: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.mappings: list[tuple[UUID, str]] = []  # (chunk_id, code)
        self.figures: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.weakness: list[dict[str, Any]] = []
        self.locked: set[UUID] = set()
        self.viva_exams: dict[UUID, dict[str, Any]] = {}

    # ---- seeding helpers -------------------------------------------------
    def add_sba(self, owner: UUID, code: str | None, chunk_id: UUID | None = None,
                kind: str = "sba") -> UUID:
        question_id = self.add_question(owner, code)
        cite = [{"ref": "E1", "kind": "chunk", "chunk_id": str(chunk_id or uuid4())}]
        self.questions[question_id][1].update({
            "type": kind, "exam_tags": ["fcps2_theory"], "topic": "PAP",
            "stem": f"Synthetic stem {question_id}?", "figure_id": None,
            "options": [_option(t) for t in "ABCDE"] if kind == "sba" else [],
            "answer": {"key": 0} if kind == "sba" else {"marking_scheme": [], "model_answer": "M"},
            "explanation": "Crazy paving.", "citations": cite, "quality": {"passed": True},
            "agent_version": "v1", "created_at": datetime(2026, 9, 1, tzinfo=UTC)})
        return question_id

    def map_chunk(self, chunk_id: UUID, code: str) -> None:
        self.mappings.append((chunk_id, code))

    def add_figure(self, owner: UUID, chunk_id: UUID) -> UUID:
        figure_id = uuid4()
        chunk = self.chunks[chunk_id][1]
        self.figures[figure_id] = (owner, {
            "id": figure_id, "source_id": chunk["source_id"], "source_title": "Synthetic chest",
            "page_no": chunk["page_from"], "caption": "Synthetic HRCT", "description": "GGO",
            "modality": "CT", "has_image": True})
        return figure_id

    # ---- sessions -----------------------------------------------------------
    async def get_session(self, user_id: UUID, day: date) -> dict[str, Any] | None:
        return next((s for owner, s in self.sessions.values()
                     if owner == user_id and s["session_date"] == day), None)

    async def get_session_by_id(self, user_id: UUID, session_id: UUID) -> dict[str, Any] | None:
        found = self.sessions.get(session_id)
        return found[1] if found and found[0] == user_id else None

    async def create_session(self, user_id: UUID, day: date, versions: tuple[int, int],
                             steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        existing = await self.get_session(user_id, day)
        if existing is not None:
            return existing
        row = {"id": uuid4(), "session_date": day, "session_version": versions[0],
               "plan_version": versions[1], "status": "active", "summary": None,
               "created_at": datetime.now(UTC), "completed_at": None,
               "steps": [{"step_no": s["step_no"], "kind": s["kind"], "status": "pending",
                          "minutes": s["minutes"], "payload": dict(s["payload"]), "result": {},
                          "started_at": None, "deadline_at": None, "completed_at": None}
                         for s in steps]}
        self.sessions[row["id"]] = (user_id, row)
        return row

    async def update_step(self, user_id: UUID, session_id: UUID, step_no: int,
                          changes: Mapping[str, Any]) -> None:
        row = await self.get_session_by_id(user_id, session_id)
        assert row is not None
        step = next(s for s in row["steps"] if s["step_no"] == step_no)
        step.update(changes)

    async def finish_session(self, user_id: UUID, session_id: UUID,
                             summary: Mapping[str, Any], now: datetime) -> None:
        row = await self.get_session_by_id(user_id, session_id)
        if row is not None and row["status"] == "active":
            row.update(status="completed", completed_at=now, summary=dict(summary))

    async def completed_sessions(self, user_id: UUID, since: date) -> list[dict[str, Any]]:
        return sorted(({"session_date": s["session_date"], "summary": s["summary"]}
                       for owner, s in self.sessions.values() if owner == user_id
                       and s["status"] == "completed" and s["session_date"] >= since),
                      key=lambda r: r["session_date"])

    # ---- material -----------------------------------------------------------
    async def cards_by_ids(self, user_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
        return [c for c in self._mine(user_id) if c["id"] in set(ids)]

    async def figures_by_ids(self, user_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
        return [f for owner, f in self.figures.values() if owner == user_id and f["id"] in ids]

    def _learned(self, user_id: UUID) -> set[str]:
        return {c for owner, s in self.sessions.values() if owner == user_id
                for st in s["steps"] if st["kind"] == "learn" and st["status"] == "done"
                for c in st["payload"]["chunk_ids"]}

    async def learn_material(self, user_id: UUID, codes: Sequence[str], limit: int,
                             figures: int) -> tuple[list[str], list[str]]:
        learned = self._learned(user_id)
        chunks = [cid for cid, code in self.mappings if code in codes
                  and self.chunks[cid][0] == user_id and str(cid) not in learned][:limit]
        near = [fid for fid, (owner, f) in self.figures.items() if owner == user_id and any(
            f["source_id"] == self.chunks[c][1]["source_id"] for c in chunks)][:figures]
        return [str(c) for c in chunks], [str(f) for f in near]

    def _last_attempt(self, user_id: UUID, question_id: UUID) -> datetime | None:
        times = [a["created_at"] for a in self.attempts
                 if a["user_id"] == user_id and a["question_id"] == question_id]
        return max(times) if times else None

    async def question_candidates(self, user_id: UUID,
                                  types: Sequence[str]) -> list[dict[str, Any]]:
        return [{"question_id": qid, "type": q["type"], "curriculum_code": q["curriculum_code"],
                 "last_attempt_at": self._last_attempt(user_id, qid)}
                for qid, (owner, q) in self.questions.items()
                if owner == user_id and q["status"] == "active" and q["type"] in types
                and qid not in self.locked]

    async def questions_by_ids(self, user_id: UUID,
                               ids: Sequence[UUID]) -> dict[str, dict[str, Any]]:
        return {str(qid): q for qid, (owner, q) in self.questions.items()
                if owner == user_id and qid in set(ids)}

    async def question_locked(self, user_id: UUID, question_id: UUID) -> bool:
        return question_id in self.locked

    # ---- weakness loop --------------------------------------------------------
    async def open_retests(self, user_id: UUID, limit: int) -> list[dict[str, Any]]:
        return [e for e in self.weakness if e["user_id"] == user_id
                and e["retested_at"] is None and e["question_id"] is not None][:limit]

    def _weak_card(self, user_id: UUID, question: Mapping[str, Any], now: datetime) -> UUID:
        earlier = [e["card_id"] for e in self.weakness if e["question_id"] == question["id"]
                   and e["card_id"] is not None]
        if earlier:
            card = self.cards[earlier[-1]][1]
            card["due_at"] = min(card["due_at"], weakness.due_at(now))
            return UUID(str(card["id"]))
        card_id = uuid4()
        self.cards[card_id] = (user_id, {
            "id": card_id, "curriculum_code": weakness.card_code(question["curriculum_code"]),
            **weakness.card_text(question), "origin": "weakness", "state": "learning",
            "stability": 0.0, "difficulty": 0.0, "due_at": weakness.due_at(now),
            "last_review_at": None, "reps": 0, "lapses": 0, "created_at": now,
            "source_id": uuid4(), "source_chunk_id": None,
            "citation": {"source_id": str(uuid4()), "source_title": "Synthetic",
                         "page_from": 1, "page_to": 1, "block_refs": []}})
        return card_id

    async def record_sba(self, user_id: UUID, question: Mapping[str, Any],
                         graded: Mapping[str, Any], confidence: int | None,
                         session_id: UUID, now: datetime) -> UUID | None:
        attempt_id = uuid4()
        self.attempts.append({"id": attempt_id, "user_id": user_id,
                              "question_id": question["id"], "score": graded["score"],
                              "max_score": graded["max_score"], "created_at": now,
                              "confidence": confidence})
        for event in self.weakness:
            if event["question_id"] == question["id"] and event["retested_at"] is None:
                event["retested_at"] = now
        if not graded["correct"]:
            self.weakness.append({
                "id": uuid4(), "user_id": user_id, "kind": "sba_wrong", "ref_id": attempt_id,
                "question_id": question["id"], "retested_at": None,
                "card_id": self._weak_card(user_id, question, now),
                "retest_by": weakness.retest_by(now)})
        return attempt_id

    async def submit_viva(self, user_id: UUID, question: Mapping[str, Any],
                          answer: str) -> dict[str, Any] | None:
        exam_id = uuid4()
        item = {"question_id": str(question["id"]), "status": "pending", "score": None,
                "citations": question["citations"]}
        self.viva_exams[exam_id] = {"id": exam_id, "owner": user_id,
                                    "result": {"items": [item]}, "answer": answer}
        return self.viva_exams[exam_id]

    async def viva_exam(self, user_id: UUID, exam_id: UUID) -> dict[str, Any] | None:
        exam = self.viva_exams.get(exam_id)
        return exam if exam and exam["owner"] == user_id else None

    # ---- insights -------------------------------------------------------------
    async def coverage_stats(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        learned = self._learned(user_id)
        out: dict[str, dict[str, Any]] = {}
        for chunk_id, code in self.mappings:
            if self.chunks[chunk_id][0] != user_id:
                continue
            row = out.setdefault(code, {"curriculum_code": code, "material": 0, "studied": 0,
                                        "score": 0.0, "max_score": 0.0})
            row["material"] += 1
            row["studied"] += str(chunk_id) in learned
        return list(out.values())

    async def rated_attempts(self, user_id: UUID, since: datetime) -> list[dict[str, Any]]:
        return [{"confidence": a["confidence"], "score": a["score"],
                 "max_score": a["max_score"]} for a in self.attempts
                if a["user_id"] == user_id and a.get("confidence") and a["created_at"] >= since]
