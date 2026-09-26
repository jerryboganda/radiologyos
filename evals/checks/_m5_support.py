"""Shared wiring for the M5 assessment gate: durable routers over an in-memory table set.

The durable exam and question code (``apps/api/app/assessment/exams.py`` and
``store.py``) talks SQL through an ``AsyncSession``. ``FakeDb`` answers exactly
the statements that code issues, honouring the same ``WHERE`` scoping (owner,
revision compare-and-set, ``submitted_at IS NULL``, the attempts unique key),
and fails loudly on any statement it does not recognise, so the service and
router logic run unchanged. One ``FakeDb`` per tenant stands in for the
tenant's RLS-bound session; the database RLS proofs for these tables run in
``evals/checks/test_assessment_live.py`` and ``test_assessment_depth_live.py``.

All content is synthetic.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from apps.api.app.api import assessment as assessment_api
from apps.api.app.api import exams as exams_api
from apps.api.app.assessment import generation
from apps.api.app.security.principal import Principal
from apps.api.tests.test_assessment_validation import EXCERPTS, sba_item
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from packages.assessment.models import QuestionCheck

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
TENANT_A = UUID("20000000-0000-4000-8000-0000000000a5")
TENANT_B = UUID("20000000-0000-4000-8000-0000000000b5")
OWNER_A = UUID("10000000-0000-4000-8000-0000000000a5")
OWNER_B = UUID("10000000-0000-4000-8000-0000000000b5")
PASS = QuestionCheck.model_validate({
    "single_best_answer": True, "key_supported": True, "no_cueing": True,
    "distractors_plausible": True, "difficulty_agrees": True, "verdict": "pass",
    "reasons": []})
PUBLIC_FIELDS = {"id", "type", "exam_tags", "topic", "stem", "options", "figure_id",
                 "figure_image_path", "status", "checked", "difficulty", "created_at", "stages"}
_OPTION_SETS = (
    ("Pulmonary alveolar proteinosis", "Pulmonary oedema", "Pneumocystis pneumonia",
     "ARDS", "Sarcoidosis"),
    ("Lipoid pneumonia", "Alveolar haemorrhage", "Mucinous adenocarcinoma",
     "Organising pneumonia", "Drug toxicity"),
)


def question_row(index: int, key: int | None = None) -> dict[str, Any]:
    """A checker-passed, cited SBA row with a fixed id and a key that varies by index."""
    texts = _OPTION_SETS[index % 2]
    options = [{"text": f"{t} ({index})", "explanation": f"because {t}", "citations": ["E1"]}
               for t in texts]
    item = sba_item(options=options, key_index=index % 5 if key is None else key,
                    topic=f"Synthetic topic {index % 3}", explanation="Crazy paving is cited.")
    row = generation.to_row(item, PASS, EXCERPTS, "fcps2_theory")
    return {**row, "id": UUID(int=0xA000 + index), "created_at": NOW, "status_reason": None}


class Clock:
    now = NOW


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, Any] | None:
        return dict(self.rows[0]) if self.rows else None

    def __iter__(self) -> Iterator[Any]:
        return iter(self.rows)

    def scalar_one(self) -> Any:
        (row,) = self.rows
        return next(iter(row.values()))

    def scalar_one_or_none(self) -> Any:
        return next(iter(self.rows[0].values())) if self.rows else None


class _Row(dict[str, Any]):
    """A mapping row that also supports positional access, like SQLAlchemy's Row."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class FakeDb:
    """One tenant's questions, exams, and attempts, scoped per owner like the SQL."""

    def __init__(self) -> None:
        self.questions: dict[UUID, tuple[UUID, dict[str, Any]]] = {}
        self.exams: dict[UUID, dict[str, Any]] = {}
        self.attempts: list[dict[str, Any]] = []

    def add_question(self, owner: UUID, row: dict[str, Any]) -> dict[str, Any]:
        self.questions[row["id"]] = (owner, row)
        return row

    def owned(self, user: UUID) -> list[dict[str, Any]]:
        return [row for owner, row in self.questions.values() if owner == user]

    def attempts_of(self, user: UUID) -> list[dict[str, Any]]:
        return [a for a in self.attempts if a["user_id"] == user]

    async def commit(self) -> None:
        return None

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        sql = " ".join(str(statement).split())
        for marker, handler in _HANDLERS:
            if marker in sql:
                return _Result(handler(self, params))
        raise AssertionError(f"FakeDb does not model this statement: {sql[:80]}")

    # ---- questions ------------------------------------------------------
    def _question(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(q) for q in self.owned(p["u"]) if q["id"] == p["q"]]

    def _questions(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(q) for q in self.owned(p["u"]) if q["id"] in set(p["ids"])]

    def _pick(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [q for q in self.owned(p["u"]) if q["status"] == "active"
                and q["type"] in p["types"] and (not p.get("tag") or p["tag"] in q["exam_tags"])]
        return [_Row(id=q["id"], type=q["type"]) for q in rows[: p["n"]]]

    def _list(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [q for q in self.owned(p["u"]) if all(
            q[c] == p[c] for c in ("type", "status") if c in p)]
        rows.sort(key=lambda q: (q["created_at"], str(q["id"])), reverse=True)
        return [dict(q) for q in rows[p["o"]: p["o"] + p["n"]]]

    # ---- exams ----------------------------------------------------------
    def _insert_exam(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        exam_id = UUID(int=0xE000 + len(self.exams))
        self.exams[exam_id] = {
            "id": exam_id, "user_id": p["u"], "mode": p["mode"],
            "config": json.loads(p["config"]), "question_ids": list(p["ids"]),
            "started_at": p["started"], "deadline_at": p["deadline"], "submitted_at": None,
            "revision": 0, "answers": {}, "text_answers": {}, "result": None,
            "created_at": p["started"]}
        return [{"id": exam_id}]

    def _mine(self, p: dict[str, Any]) -> dict[str, Any] | None:
        exam = self.exams.get(p["e"])
        return exam if exam is not None and exam["user_id"] == p["u"] else None

    def _load_exam(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        exam = self._mine(p)
        return [{k: v for k, v in exam.items() if k != "user_id"}] if exam else []

    def _save_answers(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        exam = self._mine(p)
        if exam is None or exam["revision"] != p["r"] or exam["submitted_at"] is not None:
            return []
        exam.update(answers=json.loads(p["a"]), text_answers=json.loads(p["x"]),
                    revision=exam["revision"] + 1)
        return [{k: exam[k] for k in ("revision", "answers", "text_answers", "deadline_at")}]

    def _submit(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        exam = self._mine(p)
        if exam is not None and exam["submitted_at"] is None:
            exam.update(submitted_at=p["s"], result=json.loads(p["r"]))
        return []

    def _list_exams(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        mine = [e for e in self.exams.values() if e["user_id"] == p["u"]]
        mine.sort(key=lambda e: e["started_at"], reverse=True)
        return [{k: v for k, v in e.items() if k != "user_id"} for e in mine[: p["n"]]]

    def _in_open_exam(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"one": 1} for e in self.exams.values()
                if e["user_id"] == p["u"] and e["submitted_at"] is None
                and UUID(str(p["q"])) in e["question_ids"]
                and (e["deadline_at"] is None or e["deadline_at"] > Clock.now)]

    def _insert_attempt(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        if p["e"] is not None and any(a["exam_id"] == p["e"] and a["question_id"] == p["q"]
                                      for a in self.attempts):
            return []  # ON CONFLICT (tenant_id, exam_id, question_id) DO NOTHING
        attempt_id = UUID(int=0xF000 + len(self.attempts))
        self.attempts.append({"id": attempt_id, "user_id": p["u"], "question_id": p["q"],
                              "exam_id": p["e"], "score": p["score"], "max_score": p["max"],
                              "response": json.loads(p["response"]), "graded_by": p["by"]})
        return [{"id": attempt_id}]


_HANDLERS = (
    ("INSERT INTO exams", FakeDb._insert_exam),
    ("UPDATE exams SET answers", FakeDb._save_answers),
    ("UPDATE exams SET submitted_at", FakeDb._submit),
    ("SELECT 1 FROM exams", FakeDb._in_open_exam),
    ("FROM exams WHERE id = :e AND user_id = :u", FakeDb._load_exam),
    ("FROM exams WHERE user_id = :u ORDER BY", FakeDb._list_exams),
    ("INSERT INTO attempts", FakeDb._insert_attempt),
    ("FROM questions WHERE id = ANY(:ids)", FakeDb._questions),
    ("FROM questions WHERE id = :q", FakeDb._question),
    ("SELECT id, type FROM questions", FakeDb._pick),
    ("FROM questions WHERE user_id = :u", FakeDb._list),
)


class Harness:
    """Durable assessment and exam routers over one ``FakeDb`` per tenant."""

    def __init__(self, monkeypatch: Any) -> None:
        Clock.now = NOW
        self.user, self.tenant = OWNER_A, TENANT_A
        self.dbs: defaultdict[UUID, FakeDb] = defaultdict(FakeDb)
        self.weakness: list[tuple[Any, ...]] = []
        self.enqueued: list[tuple[Any, ...]] = []
        for module in ("apps.api.app.assessment.exams", "apps.api.app.api.exams",
                       "apps.api.app.api.assessment"):
            monkeypatch.setattr(f"{module}.now_utc", lambda: Clock.now)

        async def after_sba(*args: Any) -> None:
            self.weakness.append(args)

        monkeypatch.setattr("apps.api.app.study.weakness_sql.after_sba", after_sba)
        monkeypatch.setattr(exams_api, "enqueue_grading", lambda *a: self.enqueued.append(a))
        monkeypatch.setattr(exams_api, "enqueue_stats", lambda *a: self.enqueued.append(a))
        self.client = TestClient(self._app())

    def _app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(assessment_api.router)
        app.include_router(exams_api.router)

        def principal() -> Principal:
            return Principal(self.user, self.tenant)

        async def session(
            caller: Annotated[Principal, Depends(assessment_api.principal_context)],
        ) -> AsyncIterator[FakeDb]:
            yield self.dbs[caller.tenant_id]

        app.dependency_overrides[assessment_api.principal_context] = principal
        app.dependency_overrides[assessment_api.tenant_db_session] = session
        return app

    @property
    def db(self) -> FakeDb:
        return self.dbs[TENANT_A]

    def seed(self, count: int = 8, owner: UUID = OWNER_A,
             tenant: UUID = TENANT_A) -> list[dict[str, Any]]:
        return [self.dbs[tenant].add_question(owner, question_row(i)) for i in range(count)]

    def act_as(self, user: UUID, tenant: UUID) -> None:
        self.user, self.tenant = user, tenant

    def create_exam(self, count: int = 5, minutes: int = 30) -> dict[str, Any]:
        response = self.client.post("/v1/exams", json={
            "mode": "exam", "count": count, "time_limit_minutes": minutes})
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    def autosave(self, exam_id: str, revision: int, answers: dict[str, int | None]) -> Any:
        return self.client.put(f"/v1/exams/{exam_id}/answers",
                               json={"revision": revision, "answers": answers})

    def submit(self, exam_id: str) -> Any:
        return self.client.post(f"/v1/exams/{exam_id}/submit")

    def attempt(self, question_id: Any, option: int | None) -> Any:
        return self.client.post(f"/v1/questions/{question_id}/attempt",
                                json={"selected_option": option})

    def key_of(self, question_id: str) -> int:
        return int(self.db.questions[UUID(question_id)][1]["answer"]["key"])
