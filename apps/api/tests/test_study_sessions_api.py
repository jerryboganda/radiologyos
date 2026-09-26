"""HTTP contract for the Today session runner, the weakness loop and progress insights
(in-memory repository, fixed clock, no database, no model)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import exams as exams_api
from apps.api.app.api import study
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.tests.session_fakes import MemorySessionRepo
from fastapi.testclient import TestClient

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
             / "20260926_0016_study_sessions.py")
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)  # 11:00 in Karachi
USER = UUID("10000000-0000-4000-8000-000000000021")
OTHER = UUID("10000000-0000-4000-8000-000000000022")
TENANT = UUID("20000000-0000-4000-8000-000000000021")


class Who:
    user = USER
    now = NOW


@pytest.fixture
def repo() -> Iterator[MemorySessionRepo]:
    memory = MemorySessionRepo()
    Who.user, Who.now = USER, NOW
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.principal_context] = lambda: Principal(Who.user, TENANT)
    app.dependency_overrides[study.get_now] = lambda: Who.now
    yield memory
    app.dependency_overrides.clear()


@pytest.fixture
def client(repo: MemorySessionRepo) -> TestClient:
    client = TestClient(app)
    body = {"exam_date": (NOW.date() + timedelta(days=120)).isoformat(),
            "exam_targets": ["fcps2_theory"], "daily_minutes": 90, "timezone": "Asia/Karachi"}
    assert client.put("/v1/study/profile", json=body).status_code == 200
    return client


def _seed(repo: MemorySessionRepo, owner: UUID = USER, sba: int = 12) -> dict[str, Any]:
    for code, weight in (("CHEST", 0.9), ("NEURO", 0.1)):  # CHEST becomes the focus topic
        repo.weights.append((owner, {"exam_target": "fcps2_theory", "curriculum_code": code,
                                     "weight": weight}))
    chunk = repo.add_chunk(owner)
    repo.map_chunk(chunk, "CHEST")
    figure = repo.add_figure(owner, chunk)
    card_chunk = repo.add_chunk(owner, text="Tree in bud.", heading="TB")
    card_id = uuid4()
    repo.cards[card_id] = (owner, {
        "id": card_id, "curriculum_code": "CHEST", "topic": "TB", "front": "Tree in bud?",
        "back": "Endobronchial spread.", "origin": "manual", "source_id": uuid4(),
        "source_chunk_id": card_chunk,
        "citation": {"source_id": str(uuid4()), "source_title": "S", "page_from": 1,
                     "page_to": 1, "block_refs": []},
        "state": "review", "stability": 3.0, "difficulty": 5.0, "due_at": NOW - timedelta(hours=1),
        "last_review_at": NOW - timedelta(days=3), "reps": 1, "lapses": 0,
        "created_at": NOW - timedelta(days=3)})
    questions = [repo.add_sba(owner, "CHEST", chunk) for _ in range(sba)]
    return {"chunk": chunk, "figure": figure, "questions": questions}


def _probability_keys(value: Any) -> list[str]:
    """Every JSON key that mentions a probability (there must be none)."""
    if isinstance(value, dict):
        return [k for k in value if "probab" in k.lower()] + [
            key for item in value.values() for key in _probability_keys(item)]
    if isinstance(value, list):
        return [key for item in value for key in _probability_keys(item)]
    return []


def _step(view: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(s for s in view["steps"] if s["kind"] == kind)


def _url(view: dict[str, Any], step: dict[str, Any], action: str) -> str:
    return f"/v1/study/sessions/{view['id']}/steps/{step['step_no']}/{action}"


def test_session_and_insights_need_a_profile(
    repo: MemorySessionRepo,
) -> None:
    anonymous_profile = TestClient(app)
    assert anonymous_profile.get("/v1/study/sessions/today").status_code == 409
    assert anonymous_profile.get("/v1/study/insights").status_code == 409


def test_today_session_is_sequenced_cited_and_idempotent(
    client: TestClient, repo: MemorySessionRepo
) -> None:
    seeded = _seed(repo)
    first = client.get("/v1/study/sessions/today")
    assert first.status_code == 200
    view = first.json()
    assert [s["kind"] for s in view["steps"]] == ["review", "learn", "test", "viva"]
    assert view["current_step"] == 1 and view["progress"] == {"done": 0, "total": 4}
    review, learn, test = _step(view, "review"), _step(view, "learn"), _step(view, "test")
    assert review["review"]["total"] == 1 and review["review"]["cards"][0]["citation"]
    assert learn["learn"]["chunks"][0]["chunk_id"] == str(seeded["chunk"])
    assert learn["learn"]["chunks"][0]["citation"]["page_from"] == 1
    assert learn["learn"]["figures"][0]["citation"]["kind"] == "figure"
    assert test["test"]["total"] == 12 and test["test"]["results"] == []  # the whole bank
    assert "key" not in str(test["test"]["questions"][0]) and not _probability_keys(view)
    viva = _step(view, "viva")["viva"]
    assert viva["mode"] == "self_review" and viva["citations"][0]["page_from"] == 1
    again = client.get("/v1/study/sessions/today").json()
    assert again["id"] == view["id"] and again["steps"] == view["steps"]
    assert len(repo.sessions) == 1


def test_sba_answers_resume_and_feed_the_weakness_loop(
    client: TestClient, repo: MemorySessionRepo
) -> None:
    _seed(repo)
    view = client.get("/v1/study/sessions/today").json()
    test = _step(view, "test")
    started = client.post(_url(view, test, "start")).json()
    assert _step(started, "test")["deadline_at"] is not None
    qid = test["test"]["questions"][0]["id"]
    wrong = client.post(_url(view, test, "answer"),
                        json={"question_id": qid, "selected_option": 2, "confidence": 3})
    assert wrong.status_code == 200
    result = _step(wrong.json(), "test")["test"]["results"][0]
    assert result["correct"] is False and result["key"] == 0 and result["citations"]
    assert result["confidence"] == 3
    # Idempotent: the first answer stands and no second attempt is written.
    client.post(_url(view, test, "answer"), json={"question_id": qid, "selected_option": 0})
    assert len(repo.attempts) == 1
    weak_cards = [c for _, c in repo.cards.values() if c["origin"] == "weakness"]
    assert len(weak_cards) == 1 and weak_cards[0]["due_at"] <= NOW + timedelta(days=2)
    assert repo.weakness[0]["retest_by"] == NOW + timedelta(days=2)
    resumed = client.get("/v1/study/sessions/today").json()
    assert _step(resumed, "test")["test"]["answered"] == 1 and resumed["current_step"] == 1
    # Tomorrow's session re-tests the missed question first.
    Who.now = NOW + timedelta(days=1)
    tomorrow = client.get("/v1/study/sessions/today").json()
    block = _step(tomorrow, "test")["test"]
    assert tomorrow["id"] != view["id"] and block["questions"][0]["id"] == qid
    assert block["retests"] == 1


def test_timed_block_refuses_late_answers_and_bad_input(
    client: TestClient, repo: MemorySessionRepo
) -> None:
    _seed(repo)
    view = client.get("/v1/study/sessions/today").json()
    test = _step(view, "test")
    client.post(_url(view, test, "start"))
    ids = [q["id"] for q in test["test"]["questions"]]
    assert client.post(_url(view, test, "answer"), json={"question_id": ids[0]}).status_code \
        == 422
    assert client.post(_url(view, test, "answer"), json={
        "question_id": str(uuid4()), "selected_option": 0}).status_code == 422
    assert client.post(_url(view, _step(view, "learn"), "answer"),
                       json={"answer_text": "x"}).status_code == 422
    assert client.post(f"/v1/study/sessions/{view['id']}/steps/0/start").status_code == 422
    repo.locked.add(UUID(ids[1]))
    assert client.post(_url(view, test, "answer"), json={
        "question_id": ids[1], "selected_option": 0}).status_code == 409
    Who.now = NOW + timedelta(minutes=19)  # 12 items x 1.5 min = 18 min, plus 30 s grace
    late = client.post(_url(view, test, "answer"),
                       json={"question_id": ids[2], "selected_option": 0})
    assert late.status_code == 409


def test_graded_viva_is_queued_for_the_existing_grader(
    client: TestClient, repo: MemorySessionRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed(repo)
    repo.add_sba(USER, "CHEST", seeded["chunk"], kind="viva")
    queued: list[tuple[Any, ...]] = []
    monkeypatch.setattr(exams_api, "enqueue_grading", lambda *args: queued.append(args))
    view = client.get("/v1/study/sessions/today").json()
    viva = _step(view, "viva")
    assert viva["viva"]["mode"] == "graded" and viva["viva"]["question"]["type"] == "viva"
    answered = client.post(_url(view, viva, "answer"), json={"answer_text": "Crazy paving."})
    body = _step(answered.json(), "viva")
    assert body["status"] == "done" and body["viva"]["status"] == "pending"
    assert body["viva"]["citations"] and len(queued) == 1
    assert queued[0][0] == TENANT and queued[0][2] == [body["viva"]["question"]["id"]]


def test_completion_skips_open_steps_freezes_summary_and_clears_tomorrows_plan(
    client: TestClient, repo: MemorySessionRepo
) -> None:
    _seed(repo)
    view = client.get("/v1/study/sessions/today").json()
    learn = _step(view, "learn")
    done = client.post(_url(view, learn, "complete")).json()
    assert _step(done, "learn")["status"] == "done"
    skipped = client.post(_url(view, _step(view, "review"), "complete") + "?skip=true").json()
    assert _step(skipped, "review")["status"] == "skipped"
    tomorrow = NOW.date() + timedelta(days=1)
    repo.plans[(USER, tomorrow)] = {"plan_version": 2, "blocks": [], "detail": {},
                                    "generated_at": NOW}
    url = f"/v1/study/sessions/{view['id']}/complete"
    finished = client.post(url).json()
    assert finished["status"] == "completed" and finished["current_step"] is None
    assert {s["status"] for s in finished["steps"]} == {"done", "skipped"}
    assert finished["summary"]["steps_done"] == 1 and "weighted_coverage" in finished["summary"]
    assert (USER, tomorrow) not in repo.plans
    assert client.post(url).json()["summary"] == finished["summary"]
    assert client.post(_url(view, _step(view, "test"), "start")).status_code == 409


def test_another_users_session_is_not_found(client: TestClient, repo: MemorySessionRepo) -> None:
    _seed(repo)
    view = client.get("/v1/study/sessions/today").json()
    Who.user = OTHER
    step = view["steps"][0]
    assert client.post(_url(view, step, "start")).status_code == 404
    assert client.post(_url(view, step, "complete")).status_code == 404
    assert client.post(f"/v1/study/sessions/{view['id']}/complete").status_code == 404
    assert client.post(_url(view, _step(view, "test"), "answer"), json={
        "question_id": str(uuid4()), "selected_option": 0}).status_code == 404
    assert client.get("/v1/study/sessions/today").status_code == 409  # no profile of theirs


def test_a_card_rated_again_enters_the_weakness_loop(
    client: TestClient, repo: MemorySessionRepo
) -> None:
    _seed(repo)
    card = next(c for _, c in repo.cards.values())
    assert client.post(f"/v1/study/cards/{card['id']}/review", json={"rating": 1}).status_code \
        == 200
    assert client.post(f"/v1/study/cards/{card['id']}/review", json={"rating": 3}).status_code \
        == 200
    assert [lapse[1] for lapse in repo.lapses] == [card["id"]]


def test_insights_show_heatmap_projection_and_calibration(
    client: TestClient, repo: MemorySessionRepo
) -> None:
    _seed(repo)
    view = client.get("/v1/study/sessions/today").json()
    test = _step(view, "test")
    for index, question in enumerate(test["test"]["questions"]):
        client.post(_url(view, test, "answer"), json={
            "question_id": question["id"], "selected_option": 1 if index < 8 else 0,
            "confidence": 3})
    client.post(_url(view, _step(view, "learn"), "complete"))
    response = client.get("/v1/study/insights")
    assert response.status_code == 200
    body = response.json()
    assert not _probability_keys(body)
    chest = next(r for r in body["heatmap"] if r["code"] == "CHEST")
    # System-level mappings land in the system's "General" cell once it has topics.
    general = next(c for c in chest["cells"] if c["code"] == "CHEST")
    assert general["coverage"] == 1.0 and len(body["heatmap"]) >= 16
    assert body["projection"]["status"] == "insufficient_history"
    assert body["calibration"]["verdict"] == "overconfident"
    assert body["calibration"]["confident_wrong"] == 8


def test_routes_require_identity() -> None:
    app.dependency_overrides.clear()
    anonymous = TestClient(app)
    sid = uuid4()
    assert anonymous.get("/v1/study/sessions/today").status_code == 401
    assert anonymous.get("/v1/study/insights").status_code == 401
    assert anonymous.post(f"/v1/study/sessions/{sid}/complete").status_code == 401
    assert anonymous.post(f"/v1/study/sessions/{sid}/steps/1/answer",
                          json={"answer_text": "x"}).status_code == 401


def test_migration_is_expand_only_with_forced_rls() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    assert 'revision = "20260926_0016"' in source
    assert 'TABLES = ("study_sessions", "study_session_steps", "weakness_events")' in source
    for statement in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                      "tenant_id = app.current_tenant_id()", "REVOKE ALL ON {table} FROM PUBLIC",
                      "UNIQUE (tenant_id, user_id, session_date)",
                      "UNIQUE (tenant_id, kind, ref_id)", "confidence smallint"):
        assert statement in upgrade
    for forbidden in ("DROP TABLE", "DROP COLUMN", "RENAME", "SECURITY DEFINER"):
        assert forbidden not in upgrade
    # The only DROP is the in-place widening of the origin check.
    assert upgrade.count("DROP ") == 1 and "'manual', 'generated', 'weakness'" in upgrade
