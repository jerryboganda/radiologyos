"""Contract tests for approved-weight planning, real mastery signals, the baseline
diagnostic, weekly reports, and the nightly replan (in-memory repository)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.api import study
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.app.study import reports, service
from apps.api.tests.study_fakes import MemoryStudyRepo
from fastapi.testclient import TestClient

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)  # Saturday, 11:00 in Karachi
USER = UUID("10000000-0000-4000-8000-000000000011")
OTHER = UUID("10000000-0000-4000-8000-000000000012")
TENANT = UUID("20000000-0000-4000-8000-000000000011")


@pytest.fixture
def repo() -> Iterator[MemoryStudyRepo]:
    memory = MemoryStudyRepo()
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.principal_context] = lambda: Principal(USER, TENANT)
    app.dependency_overrides[study.get_now] = lambda: NOW
    yield memory
    app.dependency_overrides.clear()


@pytest.fixture
def client(repo: MemoryStudyRepo) -> TestClient:
    client = TestClient(app)
    body = {"exam_date": (NOW.date() + timedelta(days=120)).isoformat(),
            "exam_targets": ["fcps2_theory"], "daily_minutes": 90, "timezone": "Asia/Karachi"}
    assert client.put("/v1/study/profile", json=body).status_code == 200
    return client


def _approve(repo: MemoryStudyRepo, user: UUID, target: str, weights: dict[str, float]) -> None:
    for code, weight in weights.items():
        repo.weights.append((user, {"exam_target": target, "curriculum_code": code,
                                    "weight": weight}))


def test_plan_and_progress_expose_the_weight_basis(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    plan = client.get("/v1/study/today").json()
    assert plan["weight_policy"] == "equal_unvalidated" and plan["weight_targets"] == []
    assert plan["plan_version"] == 2
    _approve(repo, OTHER, "fcps2_theory", {"NEURO": 0.9})  # another user's approval is ignored
    _approve(repo, USER, "frcr", {"GI": 0.9})  # not one of the profile's targets
    assert client.get("/v1/study/today?refresh=true").json()["weight_policy"] == (
        "equal_unvalidated")
    _approve(repo, USER, "fcps2_theory", {"CHEST": 0.5, "NEURO": 0.3, "GI": 0.1})
    plan = client.get("/v1/study/today?refresh=true").json()
    assert plan["weight_policy"] == "past_paper_approved"
    assert plan["weight_targets"] == ["fcps2_theory"]
    assert plan["priorities"][0]["code"] == "CHEST"
    progress = client.get("/v1/study/progress").json()
    assert progress["weight_policy"] == "past_paper_approved"
    weights = {t["code"]: t["weight"] for t in progress["topics"]}
    assert weights["CHEST"] > weights["NEURO"] > weights["GI"] == weights["MUSCULOSKELETAL"] > 0
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-4)


def test_question_attempts_feed_accuracy_and_coverage(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    right = repo.add_question(USER, "CHEST")
    repo.add_question(USER, "CHEST")
    wrong = repo.add_question(USER, "NEURO")
    repo.add_attempt(USER, right, 1.0, NOW - timedelta(days=1))
    repo.add_attempt(USER, wrong, 0.0, NOW - timedelta(days=1))
    theirs = repo.add_question(OTHER, "GI")
    repo.add_attempt(OTHER, theirs, 1.0, NOW)
    topics = {t["code"]: t for t in client.get("/v1/study/progress").json()["topics"]}
    assert topics["CHEST"]["accuracy"] == 1.0 and topics["CHEST"]["coverage"] == 0.5
    assert topics["CHEST"]["questions"] == 2 and topics["CHEST"]["attempts"] == 1
    assert topics["NEURO"]["accuracy"] == 0.0 and topics["NEURO"]["coverage"] == 1.0
    assert topics["GI"]["attempts"] == 0
    assert topics["CHEST"]["mastery"] > topics["NEURO"]["mastery"]


def test_baseline_needs_enough_mapped_questions(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    for _ in range(7):
        repo.add_question(USER, "CHEST")
    repo.add_question(USER, None)  # unmapped: cannot inform a system
    repo.add_question(USER, "GI", status="draft")
    response = client.post("/v1/study/baseline")
    assert response.status_code == 409
    assert "Generate SBA questions" in response.json()["detail"]
    assert client.get("/v1/study/baseline").status_code == 404


def _submit(repo: MemoryStudyRepo, exam_id: str, systems: dict[str, str]) -> None:
    items = [{"question_id": qid, "score": 1.0 if code == "CHEST" else 0.0, "max_score": 1.0}
             for qid, code in systems.items()]
    repo.exams[UUID(exam_id)].update(submitted_at=NOW, result={"items": items})


def test_baseline_spans_systems_and_freezes_results(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    for code in ["CHEST"] * 6 + ["NEURO"] * 3 + ["GI"]:
        repo.add_question(USER, code)
    first = client.post("/v1/study/baseline")
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "open" and body["question_count"] == 10
    assert body["systems"] == ["CHEST", "GI", "NEURO"] and body["results"] == []
    again = client.post("/v1/study/baseline")
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    systems = repo.baselines[-1][1]["systems"]
    _submit(repo, body["exam_id"], systems)
    done = client.get("/v1/study/baseline").json()
    assert done["status"] == "submitted"
    results = {r["code"]: r for r in done["results"]}
    assert results["CHEST"]["accuracy"] == 1.0 and results["CHEST"]["title"]
    assert results["GI"] == {"code": "GI", "title": results["GI"]["title"], "questions": 1,
                             "correct": 0.0, "accuracy": 0.0}
    assert client.post("/v1/study/baseline").json()["id"] != body["id"]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_weekly_report_is_stored_per_week_and_read_back(
    client: TestClient, repo: MemoryStudyRepo
) -> None:
    assert client.get("/v1/study/reports/latest").status_code == 404
    in_week = datetime(2026, 9, 16, 3, 0, tzinfo=UTC)
    for minute, (rating, state) in enumerate([(3, "review"), (1, "review"), (3, "new")]):
        repo.reviews.append({"user_id": USER, "card_id": None, "rating": rating,
                             "state_before": state, "curriculum_code": "CHEST",
                             "reviewed_at": in_week + timedelta(minutes=minute)})
    week = _run(reports.store_weekly_report(repo, USER, NOW))
    assert week == date(2026, 9, 14)
    assert _run(reports.store_weekly_report(repo, USER, NOW)) == week  # idempotent upsert
    assert len(repo.reports) == 1
    report = client.get("/v1/study/reports/latest").json()
    assert report["week_start"] == "2026-09-14" and report["week_end"] == "2026-09-20"
    assert report["reviews"] == 3 and report["minutes_studied"] == 3
    assert report["retention"]["achieved"] == 0.5 and report["retention"]["met"] is False
    assert report["planned_minutes"] == 7 * 90
    assert len(report["focus"]) == 3


def test_nightly_replan_builds_tomorrow_once(client: TestClient, repo: MemoryStudyRepo) -> None:
    first = _run(service.plan_for_tomorrow(repo, USER, NOW))
    assert first["plan_date"] == "2026-09-27"
    again = _run(service.plan_for_tomorrow(repo, USER, NOW))
    assert again["generated_at"] == first["generated_at"]
    assert len([k for k in repo.plans if k[0] == USER]) == 1
