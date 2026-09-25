from __future__ import annotations

from datetime import date, timedelta

from apps.api.app.main import app, settings
from apps.api.app.preview.service import reset_preview_state
from fastapi.testclient import TestClient
from packages.models.routing import RouteName

client = TestClient(app)
HEADERS = {
    "x-user-id": "10000000-0000-0000-0000-000000000001",
    "x-tenant-id": "20000000-0000-0000-0000-000000000002",
}


def setup_function() -> None:
    reset_preview_state()
    settings.preview_enabled = True


def teardown_function() -> None:
    settings.preview_enabled = False
    reset_preview_state()


def test_knowledge_and_tutor_are_grounded_or_explicitly_unavailable() -> None:
    client.post(
        "/v1/preview/sources",
        headers={**HEADERS, "Idempotency-Key": "knowledge"},
        json={
            "title": "Synthetic",
            "kind": "note",
            "content": "# Chest\n\nSynthetic ground-glass opacity.",
        },
    )

    concepts = client.get("/v1/preview/concepts", headers=HEADERS)
    source_id = client.get("/v1/preview/sources", headers=HEADERS).json()[0]["id"]
    extracted = client.post(f"/v1/preview/sources/{source_id}/extract", headers=HEADERS)
    claims = client.get("/v1/preview/claims", headers=HEADERS)
    tutor = client.post(
        "/v1/preview/tutor/ask",
        headers=HEADERS,
        json={"query": "ground-glass opacity"},
    )
    missing = client.post(
        "/v1/preview/tutor/ask",
        headers=HEADERS,
        json={"query": "unrelated term"},
    )

    assert concepts.status_code == 200
    assert extracted.status_code == 200
    assert claims.status_code == 200
    assert tutor.status_code == 200
    assert tutor.json()["citations"]
    assert missing.status_code == 200
    assert "do not have a grounded answer" in missing.json()["answer"]


def test_learning_flow_is_deterministic_and_cited() -> None:
    exam_date = (date.today() + timedelta(days=45)).isoformat()
    onboarding = client.post(
        "/v1/preview/onboarding",
        headers=HEADERS,
        json={"exam_date": exam_date, "hours_per_week": 8, "session_minutes": 60},
    )
    today_response = client.get("/v1/preview/today", headers=HEADERS)
    cards = client.get("/v1/preview/cards/due", headers=HEADERS)
    assert onboarding.status_code == 200
    assert onboarding.json()["phase"] == "consolidation"
    assert today_response.status_code == 200
    assert cards.status_code == 200
    assert cards.json()[0]["citation"]["source_id"]

    card_id = cards.json()[0]["id"]
    reviewed = client.post(
        f"/v1/preview/cards/{card_id}/review",
        headers=HEADERS,
        json={"rating": 3},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["id"] == card_id


def test_assessment_and_exam_flow_never_returns_keys_before_submission() -> None:
    questions = client.get("/v1/preview/questions", headers=HEADERS)
    assert questions.status_code == 200
    assert "key" not in questions.json()[0]
    practice = client.post("/v1/preview/practice?limit=2", headers=HEADERS)
    assert len(practice.json()["questions"]) == 2

    question_id = questions.json()[0]["question_id"]
    attempt = client.post(
        "/v1/preview/attempts",
        headers=HEADERS,
        json={"question_id": question_id, "selected_option": 0},
    )
    assert attempt.status_code == 200
    assert attempt.json()["grade"]["citations"]

    exam = client.post("/v1/preview/exams", headers=HEADERS)
    exam_id = exam.json()["exam_id"]
    assert client.post(f"/v1/preview/exams/{exam_id}/start", headers=HEADERS).status_code == 200
    autosave = client.post(
        f"/v1/preview/exams/{exam_id}/autosave",
        headers=HEADERS,
        json={"revision": 1, "answers": {question_id: 0}},
    )
    assert autosave.status_code == 200
    result = client.post(f"/v1/preview/exams/{exam_id}/submit", headers=HEADERS)
    assert result.status_code == 200
    assert result.json()["max_score"] == 5


def test_editor_and_admin_boundaries_are_server_enforced() -> None:
    student = client.get("/v1/preview/editor/queues", headers=HEADERS)
    admin_headers = {**HEADERS, "x-role": "org_admin"}
    queues = client.get("/v1/preview/editor/queues", headers=admin_headers)
    overview = client.get("/v1/preview/admin/overview", headers=admin_headers)

    assert student.status_code == 403
    assert queues.status_code == 200
    assert overview.status_code == 200


def test_operations_are_explicitly_non_release() -> None:
    billing = client.get("/v1/preview/billing/status", headers=HEADERS)
    markdown = client.get("/v1/preview/export/markdown", headers=HEADERS)
    capabilities = client.get("/v1/preview/capabilities", headers=HEADERS)
    audit = client.get("/v1/preview/release-audit", headers=HEADERS)

    assert billing.json()["provider"] == "mock_stripe_test_mode"
    assert markdown.json()["filename"] == "radbrain-preview.md"
    assert len(capabilities.json()["capabilities"]) == 26
    assert audit.json()["status"] == "blocked"


def test_local_model_mode_is_absent_entirely() -> None:
    """ADR 0009: online providers only, so no local-mode surface may exist."""
    assert client.get("/v1/preview/local-mode", headers=HEADERS).status_code == 404
    assert not hasattr(RouteName, "LOCAL")

