"""Viva routes over an in-memory store: auth, ownership, key hiding, lifecycle (no database)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import viva as viva_api
from apps.api.app.assessment import store, viva_evidence, viva_flow, viva_store
from apps.api.app.main import app
from apps.api.tests.test_assessment_api import USER, client  # noqa: F401
from apps.api.tests.test_assessment_validation import EXCERPTS
from apps.api.tests.viva_fakes import expected
from fastapi.testclient import TestClient
from packages.assessment.validation import Excerpt


class MemoryVivaStore:
    """Just enough of ``viva_store`` to drive the routes; rows are owner-scoped."""

    def __init__(self) -> None:
        self.sessions: dict[UUID, dict[str, Any]] = {}
        self.turns: dict[UUID, list[dict[str, Any]]] = {}

    async def insert_session(self, _s: Any, tenant: UUID, user: UUID,
                             values: dict[str, Any]) -> UUID:
        sid = uuid4()
        self.sessions[sid] = {
            "id": sid, "tenant_id": tenant, "user_id": user, "scenario": "", "level": 1,
            "miss_streak": 0, "work_turn": 0, "runs": 0, "errors": 0, "error_code": None,
            "finished_at": None, "stop_reason": None, "debrief": None, "question_id": None,
            "figure_id": None, "case_data": {}, "pipeline_version": 1, **values}
        self.turns[sid] = []
        return sid

    async def load_session(self, _s: Any, user: UUID | None, sid: UUID,
                           lock: bool = False) -> dict[str, Any] | None:
        row = self.sessions.get(sid)
        return dict(row) if row and (user is None or row["user_id"] == user) else None

    async def list_sessions(self, _s: Any, user: UUID, _n: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self.sessions.values() if r["user_id"] == user]

    async def load_turns(self, _s: Any, sid: UUID) -> list[dict[str, Any]]:
        return [dict(t) for t in self.turns.get(sid, [])]

    async def insert_turn(self, _s: Any, _t: Any, _u: Any, sid: UUID,
                          turn: dict[str, Any]) -> None:
        self.turns[sid].append({"status": "asked", "answer_text": None, "answered_at": None,
                                "evaluation": None, "hint": "", "stage": None, **turn})

    async def answer_turn(self, _s: Any, sid: UUID, turn_no: int, text: str, at: Any) -> bool:
        for turn in self.turns[sid]:
            if turn["turn_no"] == turn_no and turn["status"] == "asked":
                turn.update(status="answered", answer_text=text, answered_at=at)
                return True
        return False

    async def skip_open_turns(self, _s: Any, sid: UUID) -> None:
        for turn in self.turns[sid]:
            if turn["status"] in ("asked", "answered"):
                turn["status"] = "skipped"

    async def update_session(self, _s: Any, sid: UUID, values: dict[str, Any]) -> None:
        self.sessions[sid].update(values)

    async def touch_stale_work(self, *_: Any) -> int | None:
        return None

    async def staged_question_for_figure(self, *_: Any) -> None:
        return None


@pytest.fixture
def memory(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[MemoryVivaStore, list[Any]]]:
    fake = MemoryVivaStore()
    for name in ("insert_session", "load_session", "list_sessions", "load_turns", "insert_turn",
                 "answer_turn", "skip_open_turns", "update_session", "touch_stale_work",
                 "staged_question_for_figure"):
        monkeypatch.setattr(viva_store, name, getattr(fake, name))
    queued: list[Any] = []
    monkeypatch.setattr(viva_api, "enqueue_step", lambda *args: queued.append(args))

    async def no_vector(*_: Any) -> None:
        return None

    async def gather(*_: Any, **__: Any) -> list[Excerpt]:
        return EXCERPTS

    monkeypatch.setattr(viva_api, "query_vector", no_vector)
    monkeypatch.setattr(viva_evidence, "gather", gather)
    yield fake, queued


def _active(fake: MemoryVivaStore, user: UUID = USER, **values: Any) -> UUID:
    sid = uuid4()
    from apps.api.app.core.time import now_utc

    fake.sessions[sid] = {
        "id": sid, "tenant_id": uuid4(), "user_id": user, "kind": "viva", "style": "practice",
        "topic": "PAP", "scenario": "Look.", "evidence": [], "case_data": {}, "status": "active",
        "work": "none", "work_turn": 1, "runs": 0, "errors": 0, "error_code": None, "level": 1,
        "miss_streak": 0, "max_turns": 8, "started_at": now_utc(), "deadline_at": None,
        "finished_at": None, "stop_reason": None, "debrief": None, "figure_id": None,
        "question_id": None, **values}
    fake.turns[sid] = [{"turn_no": 1, "stage": None, "level": 1, "move": "open",
                        "prompt": "What pattern?", "hint": "", "expected": expected(),
                        "answer_text": None, "answered_at": None, "status": "asked",
                        "evaluation": None}]
    return sid


def test_viva_routes_require_authentication() -> None:
    anonymous = TestClient(app)
    sid = uuid4()
    assert anonymous.get("/v1/viva/sessions").status_code == 401
    assert anonymous.post("/v1/viva/sessions", json={"topic": "PAP"}).status_code == 401
    assert anonymous.get(f"/v1/viva/sessions/{sid}").status_code == 401
    assert anonymous.post(f"/v1/viva/sessions/{sid}/turns/1/answer",
                          json={"answer_text": "x"}).status_code == 401
    assert anonymous.post(f"/v1/viva/sessions/{sid}/end").status_code == 401


def test_create_freezes_references_and_queues_the_opening(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]]  # noqa: F811
) -> None:
    fake, queued = memory
    body = client.post("/v1/viva/sessions", json={"topic": "crazy paving",
                                                  "style": "fcps2_toacs"})
    assert body.status_code == 201
    view = body.json()
    assert (view["status"], view["work"], view["max_turns"]) == ("preparing", "pending", 6)
    stored = fake.sessions[UUID(view["id"])]
    assert all("text" not in item for item in stored["evidence"])
    assert "Crazy paving in PAP" not in str(stored["evidence"])
    assert stored["figure_id"] == EXCERPTS[0].figure_id
    assert [(args[1], args[2]) for args in queued] == [(UUID(view["id"]), 0)]


def test_create_refuses_without_material(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def figure_only(*_: Any, **__: Any) -> list[Excerpt]:
        return EXCERPTS[:1]

    async def text_only(*_: Any, **__: Any) -> list[Excerpt]:
        return EXCERPTS[1:]

    monkeypatch.setattr(viva_evidence, "gather", figure_only)
    assert client.post("/v1/viva/sessions", json={"topic": "PAP"}).json()["detail"] == \
        "no_source_material"
    monkeypatch.setattr(viva_evidence, "gather", text_only)
    refused = client.post("/v1/viva/sessions", json={"topic": "PAP", "kind": "image_case"})
    assert (refused.status_code, refused.json()["detail"]) == (422, "no_described_figure")
    assert client.post("/v1/viva/sessions", json={"kind": "viva"}).status_code == 422
    assert client.post("/v1/viva/sessions", json={"question_id": str(uuid4())}).status_code \
        == 422


def test_staged_case_from_a_question_is_guarded(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qid = uuid4()
    rubric = [{"stage": "describe", "prompt": "Describe.", "model_answer": "CT",
               "marking_scheme": [{"point": "CT", "marks": 1, "citations": [{"ref": "E1"}],
                                   "stage": "describe"}]}]
    question: dict[str, Any] = {"id": qid, "type": "seq", "answer": {}, "topic": "PAP",
                                "stem": "Look.", "citations": [{"ref": "E1"}], "figure_id": None}
    open_exam = {"value": False}

    async def get_question(*_: Any) -> dict[str, Any]:
        return question

    async def in_open_exam(*_: Any) -> bool:
        return open_exam["value"]

    monkeypatch.setattr(store, "get_question", get_question)
    monkeypatch.setattr(store, "in_open_exam", in_open_exam)
    body = {"kind": "image_case", "question_id": str(qid)}
    assert client.post("/v1/viva/sessions", json=body).json()["detail"] == "question_not_staged"
    question.update(type="image_case", answer={"stages": rubric})
    open_exam["value"] = True
    assert client.post("/v1/viva/sessions", json=body).status_code == 409
    open_exam["value"] = False
    view = client.post("/v1/viva/sessions", json=body).json()
    assert view["status"] == "active" and view["current_turn"] == 1
    assert view["turns"][0]["stage"] == "describe" and view["turns"][0]["expected"] == []
    assert "CT" not in str(view["turns"]) and memory[1] == []


def test_another_users_session_is_not_found(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]]  # noqa: F811
) -> None:
    fake, _ = memory
    theirs = _active(fake, user=uuid4())
    assert client.get(f"/v1/viva/sessions/{theirs}").status_code == 404
    assert client.post(f"/v1/viva/sessions/{theirs}/turns/1/answer",
                       json={"answer_text": "PAP"}).status_code == 404
    assert client.post(f"/v1/viva/sessions/{theirs}/end").status_code == 404
    assert client.get("/v1/viva/sessions").json() == []


def test_answer_queues_grading_and_hides_the_expected_answer(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]]  # noqa: F811
) -> None:
    fake, queued = memory
    sid = _active(fake)
    assert client.get(f"/v1/viva/sessions/{sid}").json()["turns"][0]["expected"] == []
    view = client.post(f"/v1/viva/sessions/{sid}/turns/1/answer",
                       json={"answer_text": "Crazy paving"}).json()
    assert view["work"] == "pending" and view["turns"][0]["status"] == "answered"
    assert view["turns"][0]["expected"] == [] and queued[-1][1:] == (sid, 1)
    busy = client.post(f"/v1/viva/sessions/{sid}/turns/1/answer", json={"answer_text": "x"})
    assert (busy.status_code, busy.json()["detail"]) == (409, "viva_examiner_busy")
    fake.sessions[sid]["work"] = "none"
    closed = client.post(f"/v1/viva/sessions/{sid}/turns/1/answer", json={"answer_text": "x"})
    assert closed.json()["detail"] == "viva_turn_closed"


def test_answer_after_the_deadline_finishes_the_session(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]]  # noqa: F811
) -> None:
    fake, queued = memory
    sid = _active(fake)
    fake.sessions[sid]["deadline_at"] = fake.sessions[sid]["started_at"] - timedelta(seconds=1)
    late = client.post(f"/v1/viva/sessions/{sid}/turns/1/answer", json={"answer_text": "x"})
    assert (late.status_code, late.json()["detail"]) == (409, "viva_time_expired")
    assert fake.sessions[sid]["stop_reason"] == "time_up" and queued == []
    view = client.get(f"/v1/viva/sessions/{sid}").json()
    assert view["status"] == "finished" and view["turns"][0]["status"] == "skipped"
    assert view["turns"][0]["expected"] and view["debrief"]["overall_percent"] == 0.0


def test_end_is_idempotent_and_reveals_the_transcript(
    client: TestClient, memory: tuple[MemoryVivaStore, list[Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, _ = memory
    sid = _active(fake)
    reported: list[Any] = []

    async def report(_s: Any, areas: Any) -> int:
        reported.append(areas)
        return 0

    monkeypatch.setattr(viva_flow, "report_weak_areas", report)
    first = client.post(f"/v1/viva/sessions/{sid}/end").json()
    assert first["stop_reason"] == "ended_by_candidate" and first["current_turn"] is None
    again = client.post(f"/v1/viva/sessions/{sid}/end").json()
    assert again["finished_at"] == first["finished_at"] and len(reported) == 1
    summary = client.get("/v1/viva/sessions").json()
    assert summary[0]["status"] == "finished" and summary[0]["overall_percent"] == 0.0
