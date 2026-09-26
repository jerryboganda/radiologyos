"""Fakes for the tutor routes: no database, no model (ADR 0013)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import tutor as tutor_api
from apps.api.app.library import search
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.app.tutor import repo
from packages.models.claude_code import ModelCall, ModelResult
from packages.tutor.models import GroundedAnswer

PRINCIPAL = Principal(user_id=uuid4(), tenant_id=uuid4())
NOW = datetime(2026, 9, 26, tzinfo=UTC)
CHUNK = uuid4()
FIGURE = uuid4()
HIT = {"id": CHUNK, "source_id": uuid4(), "source_title": "Synthetic deck", "page_from": 4,
       "page_to": 4, "heading": "Chest", "text": "Crazy paving.", "block_refs": []}
FIGURE_HIT = {"id": FIGURE, "source_id": uuid4(), "source_title": "Synthetic deck",
              "page_no": 5, "figure_no": 1, "caption": "Fig 1", "modality": "CT",
              "anatomy": "chest", "image_key": "k", "score": 0.5,
              "description": "Axial HRCT with crazy paving."}
SOURCE_OK = {"coverage": "full", "segments": [
    {"text": "PAP shows crazy paving.", "sources": ["S1"]}]}
JUDGE_OK = {"verdicts": [{"segment": 1, "verdict": "supported", "reason": "Stated in S1."}]}


WEB_OK = {
    "segments": [{"text": "Dermoids are T1 bright.",
                  "urls": ["https://radiopaedia.org/articles/dermoid"]}],
    "pages": [{"url": "https://radiopaedia.org/articles/dermoid",
               "summary": "Dermoid cysts contain fat and are T1 hyperintense."}],
}


def is_judge(call: ModelCall) -> bool:
    return "verdicts" in call.output_schema.get("properties", {})


def all_supported(call: ModelCall) -> dict[str, Any]:
    numbers = re.findall(r'<segment n="(\d+)"', call.user_prompt)
    return {"verdicts": [{"segment": int(n), "verdict": "supported", "reason": "Stated."}
                         for n in numbers]}


class ScriptedTransport:
    """Answers by agent: web (has WebSearch), judge (verdicts schema), or source."""

    def __init__(self, source: Any = None, web: Any = None, judge: Any = all_supported) -> None:
        self.source, self.web, self.judge = source, web, judge
        self.calls: list[ModelCall] = []

    def run(self, call: ModelCall) -> ModelResult:
        self.calls.append(call)
        if is_judge(call):
            output = self.judge(call) if callable(self.judge) else self.judge
        else:
            output = self.web if "WebSearch" in call.tools else self.source
        if isinstance(output, Exception):
            raise output
        if output is None:
            raise AssertionError("unexpected agent call")
        return ModelResult(output=output, duration_ms=1, cost_usd=0.0)

    @property
    def web_calls(self) -> list[ModelCall]:
        return [c for c in self.calls if "WebSearch" in c.tools]

    @property
    def judge_calls(self) -> list[ModelCall]:
        return [c for c in self.calls if is_judge(c)]


class FakeSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def commit(self) -> None:
        self.events.append("commit")


class FakeTransport:
    """Answers the tutor agents with ``output`` and the judge with ``judge``."""

    def __init__(self, output: dict[str, Any] | Exception,
                 judge: dict[str, Any] | Exception | None = None) -> None:
        self.output = output
        self.judge: dict[str, Any] | Exception = JUDGE_OK if judge is None else judge
        self.calls: list[ModelCall] = []
        self.session: FakeSession | None = None

    def run(self, call: ModelCall) -> ModelResult:
        assert self.session is not None and self.session.events[-1] == "rollback"
        self.calls.append(call)
        output = self.judge if is_judge(call) else self.output
        if isinstance(output, Exception):
            raise output
        return ModelResult(output=output, duration_ms=1, cost_usd=0.0)


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
        stored = repo.stored_citations(answer)  # the real jsonb array shape
        self.messages.setdefault(thread_id, []).extend([
            {"id": uuid4(), "role": "user", "content": question, "citations": [],
             "grounding": None, "agent_version": "", "created_at": NOW},
            {"id": message_id, "role": "assistant", "content": answer.text,
             "citations": stored, "grounding": answer.grounding,
             "agent_version": answer.agent_version, "created_at": NOW},
        ])
        return message_id

    async def recent_history(self, _s: Any, thread_id: UUID) -> list[Any]:
        return []

    async def thread_messages(self, _s: Any, thread_id: UUID) -> list[dict[str, Any]]:
        return self.messages.get(thread_id, [])

    async def list_threads(self, _s: Any, user_id: UUID) -> list[dict[str, Any]]:
        return [{**t, "message_count": len(self.messages.get(t["id"], []))}
                for t in self.threads.values()]


@contextmanager
def tutor_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Patch retrieval, persistence, and the transport; yield the mutable state."""
    session, fake_repo = FakeSession(), FakeRepo()
    state: dict[str, Any] = {"session": session, "repo": fake_repo, "hits": [HIT],
                             "figures": [], "transport": FakeTransport(SOURCE_OK)}

    async def fake_search(_s: Any, user_id: UUID, query: str, _v: Any, limit: int) -> Any:
        state["search"] = (user_id, query, limit)
        return state["hits"]

    async def fake_figures(_s: Any, user_id: UUID, query: str, limit: int = 12) -> Any:
        state["figure_search"] = (user_id, query, limit)
        return state["figures"]

    async def fake_set_tenant(_s: Any, tenant_id: UUID) -> None:
        session.events.append(f"tenant:{tenant_id}")

    monkeypatch.setattr(search, "hybrid_search", fake_search)
    monkeypatch.setattr(search, "search_figures", fake_figures)
    monkeypatch.setattr(tutor_api, "query_vector", lambda _q: None)
    monkeypatch.setattr(tutor_api, "set_database_tenant", fake_set_tenant)
    for name in ("get_thread", "create_thread", "add_exchange", "recent_history",
                 "thread_messages", "list_threads"):
        monkeypatch.setattr(repo, name, getattr(fake_repo, name))

    def transport() -> Any:
        if state["transport"] is None:
            return None
        state["transport"].session = session
        return state["transport"]

    app.dependency_overrides[tutor_api.principal_context] = lambda: PRINCIPAL
    app.dependency_overrides[tutor_api.tenant_db_session] = lambda: session
    app.dependency_overrides[tutor_api.model_transport] = transport
    try:
        yield state
    finally:
        app.dependency_overrides.clear()
