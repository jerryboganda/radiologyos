"""Tutor route contract with dependency overrides (no database, no model)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import tutor as tutor_api
from apps.api.app.core.config import get_settings
from apps.api.app.main import app
from apps.api.app.tutor import repo
from apps.api.tests.tutor_fakes import (
    CHUNK,
    FIGURE,
    FIGURE_HIT,
    NOW,
    PRINCIPAL,
    tutor_env,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from packages.models.claude_code import ModelCallError, UsageLimitError


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    with tutor_env(monkeypatch) as state:
        yield state


client = TestClient(app)


def test_ask_returns_cited_segments_and_persists_a_new_thread(env: dict[str, Any]) -> None:
    response = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounding"] == "sources" and body["excerpts_considered"] == 1
    citation = body["segments"][0]["citations"][0]
    assert (citation["chunk_id"], citation["page_from"]) == (str(CHUNK), 4)
    assert UUID(body["thread_id"]) in env["repo"].threads
    assert env["search"] == (PRINCIPAL.user_id, "what or is or crazy or paving", 8)
    tenant = f"tenant:{PRINCIPAL.tenant_id}"
    # no transaction during the rerank call (graph read after it) or the model calls
    assert env["session"].events == ["rollback", tenant, "rollback", tenant, "commit"]


def test_follow_up_in_thread_and_thread_reads(env: dict[str, Any]) -> None:
    first = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"}).json()
    again = client.post("/v1/tutor/ask", json={"question": "And in children?",
                                               "thread_id": first["thread_id"]})
    assert again.status_code == 200 and again.json()["thread_id"] == first["thread_id"]
    threads = client.get("/v1/tutor/threads").json()
    assert threads[0]["message_count"] == 4
    detail = client.get(f"/v1/tutor/threads/{first['thread_id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
    assert detail["messages"][1]["segments"][0]["origin"] == "sources"
    assert detail["messages"][0]["grounding"] is None


def test_unknown_thread_is_404_before_any_model_call(env: dict[str, Any]) -> None:
    response = client.post("/v1/tutor/ask", json={"question": "q??", "thread_id": str(uuid4())})
    assert response.status_code == 404 and env["transport"].calls == []
    assert client.get(f"/v1/tutor/threads/{uuid4()}").status_code == 404


def test_uncovered_question_without_web_is_not_found(env: dict[str, Any]) -> None:
    env["hits"] = []
    response = client.post("/v1/tutor/ask", json={"question": "Dermoid?", "allow_web": False})
    body = response.json()
    assert body["grounding"] == "none" and body["segments"] == []
    assert body["notice"].startswith("Not found in your sources")


@pytest.mark.parametrize(("error", "status"), [(UsageLimitError("x"), 429),
                                               (ModelCallError("y"), 502)])
def test_model_failures_map_to_clear_statuses(
    env: dict[str, Any], error: Exception, status: int
) -> None:
    env["transport"].output = error
    response = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"})
    assert response.status_code == status
    assert "commit" not in env["session"].events


def test_request_validation(env: dict[str, Any]) -> None:
    assert client.post("/v1/tutor/ask", json={"question": "x"}).status_code == 422
    assert client.post("/v1/tutor/ask", json={"question": "abc", "extra": 1}).status_code == 422


def test_missing_cli_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "claude_code_bin", "radbrain-no-such-binary")
    assert tutor_api.model_transport() is None
    with pytest.raises(HTTPException) as caught:
        tutor_api.get_transport(tutor_api.model_transport())
    assert caught.value.status_code == 503 and "Claude Code CLI" in str(caught.value.detail)


def test_missing_cli_is_503_over_http(env: dict[str, Any]) -> None:
    env["transport"] = None
    response = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"})
    assert response.status_code == 503 and "Claude Code CLI" in response.json()["detail"]


def test_lexical_query_ors_unique_terms() -> None:
    assert tutor_api.lexical_query("CT vs. MRI: CT?") == "ct or vs or mri"
    assert repo.thread_title("  a\n b ") == "a b"
    assert len(repo.thread_title("x" * 500)) == repo.TITLE_CHARS


def test_answer_carries_judge_stats_and_persists_them(env: dict[str, Any]) -> None:
    body = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"}).json()
    assert body["judge"]["status"] == "ok" and body["judge"]["supported"] == 1
    assert body["segments"][0]["support"] == "supported"
    assert "grounding_judge/v1" in body["agent_version"]
    stored = env["repo"].messages[UUID(body["thread_id"])][1]["citations"]
    assert isinstance(stored, list)  # migration 0005: CHECK jsonb_typeof = 'array'
    assert stored[0]["support"] == "supported"
    assert stored[-1] == {"kind": "judge_stats", "judge": body["judge"], "dropped_segments": 0}
    assert repo.stored_answer(stored) == (stored[:-1], body["judge"])
    detail = client.get(f"/v1/tutor/threads/{body['thread_id']}").json()
    assert detail["messages"][1]["judge"]["status"] == "ok"


def test_judge_switched_off_by_setting_labels_not_verified(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "tutor_grounding_judge", False)
    body = client.post("/v1/tutor/ask", json={"question": "What is crazy paving?"}).json()
    assert body["judge"]["status"] == "skipped"
    assert body["segments"][0]["support"] == "not_verified"
    assert len(env["transport"].calls) == 1  # no judge call


def test_figures_are_retrieved_and_cited_by_id_and_page(env: dict[str, Any]) -> None:
    env["figures"] = [FIGURE_HIT, {**FIGURE_HIT, "id": uuid4(), "description": ""}]
    env["transport"].output = {"coverage": "full", "segments": [
        {"text": "The CT shows crazy paving.", "sources": ["F1"]}]}
    body = client.post("/v1/tutor/ask", json={"question": "Crazy paving on CT?"}).json()
    assert body["figures_considered"] == 1  # the undescribed figure is not offered
    citation = body["segments"][0]["citations"][0]
    assert citation["kind"] == "figure" and citation["figure_id"] == str(FIGURE)
    assert (citation["page_from"], citation["label"]) == (5, "F1")
    assert env["figure_search"] == (PRINCIPAL.user_id, "crazy or paving or on or ct", 12)
    prompt = env["transport"].calls[0].user_prompt
    assert '<figure id="F1"' in prompt and "Axial HRCT with crazy paving." in prompt


def test_legacy_stored_segments_list_still_reads(env: dict[str, Any]) -> None:
    thread = uuid4()
    env["repo"].owners[thread] = PRINCIPAL.user_id
    env["repo"].threads[thread] = {"id": thread, "title": "Old", "created_at": NOW,
                                   "updated_at": NOW}
    env["repo"].messages[thread] = [{
        "id": uuid4(), "role": "assistant", "content": "Old answer.", "grounding": "sources",
        "agent_version": "tutor_answer/v1", "created_at": NOW,
        "citations": [{"text": "Old answer.", "origin": "sources", "citations": [
            {"kind": "source", "label": "S1", "chunk_id": str(CHUNK)}]}]}]
    message = client.get(f"/v1/tutor/threads/{thread}").json()["messages"][0]
    assert message["segments"][0]["text"] == "Old answer." and message["judge"] is None
    assert repo.stored_answer(None) == ([], None)
