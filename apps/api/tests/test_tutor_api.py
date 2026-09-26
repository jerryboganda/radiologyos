"""Tutor route contract with dependency overrides (no database, no model)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import tutor as tutor_api
from apps.api.app.core.config import get_settings
from apps.api.app.library import search
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.app.tutor import repo
from fastapi import HTTPException
from fastapi.testclient import TestClient
from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError
from packages.tutor.models import GroundedAnswer

PRINCIPAL = Principal(user_id=uuid4(), tenant_id=uuid4())
NOW = datetime(2026, 9, 26, tzinfo=UTC)
CHUNK = uuid4()


class FakeSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def commit(self) -> None:
        self.events.append("commit")


class FakeTransport:
    def __init__(self, output: dict[str, Any] | Exception) -> None:
        self.output = output
        self.calls: list[ModelCall] = []
        self.session: FakeSession | None = None

    def run(self, call: ModelCall) -> ModelResult:
        assert self.session is not None and self.session.events[-1] == "rollback"
        self.calls.append(call)
        if isinstance(self.output, Exception):
            raise self.output
        return ModelResult(output=self.output, duration_ms=1, cost_usd=0.0)


class FakeRepo:
    def __init__(self) -> None:
        self.threads: dict[UUID, dict[str, Any]] = {}
        self.messages: dict[UUID, list[dict[str, Any]]] = {}
        self.owners: dict[UUID, UUID] = {}

    async def get_thread(self, _s: Any, user_id: UUID, thread_id: UUID) -> Any:
        return self.threads.get(thread_id) if self.owners.get(thread_id) == user_id else None

    async def create_thread(self, _s: Any, tenant_id: UUID, user_id: UUID, title: str) -> UUID:
        thread_id = uuid4()
        self.owners[thread_id] = user_id
        self.threads[thread_id] = {"id": thread_id, "title": title, "created_at": NOW,
                                   "updated_at": NOW}
        return thread_id

    async def add_exchange(self, _s: Any, _t: UUID, thread_id: UUID, question: str,
                           answer: GroundedAnswer) -> UUID:
        message_id = uuid4()
        self.messages.setdefault(thread_id, []).extend([
            {"id": uuid4(), "role": "user", "content": question, "citations": [],
             "grounding": None, "agent_version": "", "created_at": NOW},
            {"id": message_id, "role": "assistant", "content": answer.text,
             "citations": [s.model_dump(mode="json") for s in answer.segments],
             "grounding": answer.grounding, "agent_version": answer.agent_version,
             "created_at": NOW},
        ])
        return message_id

    async def recent_history(self, _s: Any, thread_id: UUID) -> list[Any]:
        return []

    async def thread_messages(self, _s: Any, thread_id: UUID) -> list[dict[str, Any]]:
        return self.messages.get(thread_id, [])

    async def list_threads(self, _s: Any, user_id: UUID) -> list[dict[str, Any]]:
        return [{**t, "message_count": len(self.messages.get(t["id"], []))}
                for t in self.threads.values()]


HIT = {"id": CHUNK, "source_id": uuid4(), "source_title": "Synthetic deck", "page_from": 4,
       "page_to": 4, "heading": "Chest", "text": "Crazy paving.", "block_refs": []}


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    session, fake_repo = FakeSession(), FakeRepo()
    state: dict[str, Any] = {"session": session, "repo": fake_repo, "hits": [HIT],
                             "transport": FakeTransport({"coverage": "full", "segments": [
                                 {"text": "PAP shows crazy paving.", "sources": ["S1"]}]})}

    async def fake_search(_s: Any, user_id: UUID, query: str, _v: Any, limit: int) -> Any:
        state["search"] = (user_id, query, limit)
        return state["hits"]

    async def fake_set_tenant(_s: Any, tenant_id: UUID) -> None:
        session.events.append(f"tenant:{tenant_id}")

    monkeypatch.setattr(search, "hybrid_search", fake_search)
    monkeypatch.setattr(tutor_api, "query_vector", lambda _q: None)
    monkeypatch.setattr(tutor_api, "set_database_tenant", fake_set_tenant)
    for name in ("get_thread", "create_thread", "add_exchange", "recent_history",
                 "thread_messages", "list_threads"):
        monkeypatch.setattr(repo, name, getattr(fake_repo, name))

    def transport() -> Any:
        state["transport"].session = session
        return state["transport"]

    app.dependency_overrides[tutor_api.principal_context] = lambda: PRINCIPAL
    app.dependency_overrides[tutor_api.tenant_db_session] = lambda: session
    app.dependency_overrides[tutor_api.get_transport] = transport
    try:
        yield state
    finally:
        app.dependency_overrides.clear()


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
    assert env["session"].events == ["rollback", f"tenant:{PRINCIPAL.tenant_id}", "commit"]


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
    with pytest.raises(HTTPException) as caught:
        tutor_api.get_transport()
    assert caught.value.status_code == 503 and "Claude Code CLI" in str(caught.value.detail)


def test_lexical_query_ors_unique_terms() -> None:
    assert tutor_api.lexical_query("CT vs. MRI: CT?") == "ct or vs or mri"
    assert repo.thread_title("  a\n b ") == "a b"
    assert len(repo.thread_title("x" * 500)) == repo.TITLE_CHARS
