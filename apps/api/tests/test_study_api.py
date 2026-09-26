"""Contract tests for /v1/study with an in-memory repository and a fixed clock."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import study
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.tests.study_fakes import MemoryStudyRepo
from fastapi.testclient import TestClient

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
USER = UUID("10000000-0000-4000-8000-000000000001")
OTHER = UUID("10000000-0000-4000-8000-000000000002")
TENANT = UUID("20000000-0000-4000-8000-000000000001")


class Clock:
    now = NOW


@pytest.fixture
def repo() -> Iterator[MemoryStudyRepo]:
    memory = MemoryStudyRepo()
    Clock.now = NOW
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.principal_context] = lambda: Principal(USER, TENANT)
    app.dependency_overrides[study.get_now] = lambda: Clock.now
    yield memory
    app.dependency_overrides.clear()


@pytest.fixture
def client(repo: MemoryStudyRepo) -> TestClient:
    return TestClient(app)


def _profile(client: TestClient, **overrides: Any) -> Any:
    body = {"exam_date": (NOW.date() + timedelta(days=120)).isoformat(),
            "exam_targets": ["fcps2_theory", "fcps2_toacs"], "daily_minutes": 90,
            "timezone": "Asia/Karachi", **overrides}
    return client.put("/v1/study/profile", json=body)


def _card(client: TestClient, chunk_id: UUID, **overrides: Any) -> Any:
    body = {"chunk_id": str(chunk_id), "curriculum_code": "CHEST",
            "topic": "pulmonary alveolar proteinosis",
            "front": "Classic HRCT pattern of PAP?", "back": "Crazy paving.", **overrides}
    return client.post("/v1/study/cards", json=body)


def test_exam_date_is_required_first(client: TestClient) -> None:
    assert client.get("/v1/study/profile").status_code == 404
    assert client.get("/v1/study/today").status_code == 409
    assert client.get("/v1/study/progress").status_code == 409


def test_profile_validation(client: TestClient) -> None:
    assert _profile(client, exam_date=NOW.date().isoformat()).status_code == 422
    assert _profile(client, timezone="Mars/Olympus").status_code == 422
    assert _profile(client, exam_targets=["usmle"]).status_code == 422
    assert _profile(client, daily_minutes=5).status_code == 422
    saved = _profile(client, weekend_minutes=150)
    assert saved.status_code == 200
    body = saved.json()
    assert body["days_remaining"] == 120 and body["phase"] == "coverage_consolidation"
    assert client.get("/v1/study/profile").json()["weekend_minutes"] == 150


def test_today_plan_is_cached_and_reset_by_profile_change(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    _profile(client, weekend_minutes=120)
    first = client.get("/v1/study/today")
    assert first.status_code == 200
    plan = first.json()
    assert plan["minutes"] == 120  # 2026-09-26 is a Saturday in Asia/Karachi
    assert sum(b["minutes"] for b in plan["blocks"]) == 120
    assert "probability" not in first.text.lower()
    assert client.get("/v1/study/today").json()["generated_at"] == plan["generated_at"]
    _profile(client, weekend_minutes=60)
    assert repo.plans == {}
    assert client.get("/v1/study/today").json()["minutes"] == 60


def test_card_requires_an_owned_chunk_and_known_curriculum(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    mine = repo.add_chunk(USER)
    foreign = repo.add_chunk(OTHER)
    assert _card(client, uuid4()).status_code == 404
    assert _card(client, foreign).status_code == 404
    assert _card(client, mine, curriculum_code="NOT_A_SYSTEM").status_code == 422
    created = _card(client, mine)
    assert created.status_code == 201
    citation = created.json()["citation"]
    assert citation["chunk_id"] == str(mine) and citation["page_from"] == 1
    assert citation["block_refs"] == [{"page": 1, "block": 0}]


def test_review_loop_schedules_with_fsrs(client: TestClient, repo: MemoryStudyRepo) -> None:
    _profile(client)
    card_id = _card(client, repo.add_chunk(USER)).json()["id"]
    due = client.get("/v1/study/cards/due").json()
    assert [c["id"] for c in due] == [card_id]
    assert client.post(f"/v1/study/cards/{card_id}/review", json={"rating": 5}).status_code \
        == 422
    reviewed = client.post(f"/v1/study/cards/{card_id}/review", json={"rating": 3})
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["scheduled_days"] == 3 and body["card"]["state"] == "review"
    assert body["retention"] == 0.9
    assert client.get("/v1/study/cards/due").json() == []
    Clock.now = NOW + timedelta(days=3)
    assert [c["id"] for c in client.get("/v1/study/cards/due").json()] == [card_id]
    lapse = client.post(f"/v1/study/cards/{card_id}/review", json={"rating": 1}).json()
    assert lapse["card"]["lapses"] == 1 and lapse["scheduled_days"] == 0
    assert client.post(f"/v1/study/cards/{uuid4()}/review", json={"rating": 3}).status_code \
        == 404


def test_new_cards_respect_the_daily_cap(client: TestClient, repo: MemoryStudyRepo) -> None:
    _profile(client)
    chunk = repo.add_chunk(USER)
    for index in range(30):
        _card(client, chunk, front=f"Question {index}?")
    assert len(client.get("/v1/study/cards/due?limit=100").json()) == 25


def test_progress_reports_mastery_without_pass_probability(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    _profile(client, exam_date=(NOW.date() + timedelta(days=20)).isoformat())
    card_id = _card(client, repo.add_chunk(USER)).json()["id"]
    client.post(f"/v1/study/cards/{card_id}/review", json={"rating": 3})
    response = client.get("/v1/study/progress")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "exam_mode" and body["retention"] == 0.93
    assert body["reviews_today"] == 1 and body["cards"] == 1
    chest = next(t for t in body["topics"] if t["code"] == "CHEST")
    assert chest["coverage"] == 1.0 and chest["accuracy"] == 1.0
    assert chest["mastery"] > next(t for t in body["topics"] if t["code"] == "GI")["mastery"]
    assert len(body["topics"]) == 17  # 16 original systems + ANATOMY (ADR 0023)
    assert "pass_prob" not in response.text and "No pass probability" in body["notice"]


def test_migration_forces_rls_and_is_expand_only() -> None:
    source = (MIGRATIONS / "20260926_0006_study.py").read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    assert 'down_revision = "20260926_0005"' in source
    assert 'TABLES = ("study_profiles", "cards", "card_reviews", "study_plans")' in source
    for statement in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                      "tenant_id = app.current_tenant_id()", "REVOKE ALL ON {table} FROM PUBLIC"):
        assert statement in upgrade
    assert "DROP " not in upgrade and "RENAME" not in upgrade
    assert "citation jsonb NOT NULL" in upgrade


def test_study_routes_require_authentication() -> None:
    app.dependency_overrides.clear()
    anonymous = TestClient(app)
    assert anonymous.get("/v1/study/today").status_code == 401
    assert anonymous.put("/v1/study/profile", json={}).status_code in {401, 422}
