"""Fakes for the tutor routes: no database, no model (ADR 0013)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import tutor as tutor_api
from apps.api.app.library import rerank, search
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.app.tutor import graph, images, repo, service
from packages.library.storage import MemoryObjectStore
from packages.models.claude_code import ModelCall, ModelResult
from packages.tutor.memory import MemoryState, MemoryUpdate
from packages.tutor.models import GroundedAnswer
from packages.tutor.prompts import Turn

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


READING = {"modality": "CT chest, axial", "anatomy": "chest", "visible_text": "",
           "findings": ["Crazy paving"], "impression": "Alveolar proteinosis",
           "differentials": ["Pulmonary oedema"], "teaching_points": [], "topics": ["PAP"],
           "confidence": "medium"}
MEMORY_OK = {"summary": "Earlier the candidate asked about crazy paving."}


def agent_of(call: ModelCall) -> str:
    props = call.output_schema.get("properties", {})
    if "verdicts" in props:
        return "judge"
    if "impression" in props:
        return "vision"
    if set(props) == {"summary"}:
        return "memory"
    return "tutor"


class FakeTransport:
    """Answers the tutor agents with ``output``, the judge with ``judge``, the
    vision agent with ``vision``, and the memory agent with ``memory``."""

    def __init__(self, output: dict[str, Any] | Exception,
                 judge: dict[str, Any] | Exception | None = None) -> None:
        self.output = output
        self.judge: dict[str, Any] | Exception = JUDGE_OK if judge is None else judge
        self.vision: dict[str, Any] | Exception = READING
        self.memory: dict[str, Any] | Exception = MEMORY_OK
        self.calls: list[ModelCall] = []
        self.session: FakeSession | None = None

    def _output(self, call: ModelCall) -> dict[str, Any]:
        assert self.session is not None and self.session.events[-1] == "rollback"
        self.calls.append(call)
        output = {"judge": self.judge, "vision": self.vision, "memory": self.memory,
                  "tutor": self.output}[agent_of(call)]
        if isinstance(output, Exception):
            raise output
        return output

    def run(self, call: ModelCall) -> ModelResult:
        return ModelResult(output=self._output(call), duration_ms=1, cost_usd=0.0)

    def agents(self) -> list[str]:
        return [agent_of(call) for call in self.calls]


class StreamingFakeTransport(FakeTransport):
    """Like FakeTransport, but streams each answer's JSON text in small deltas."""

    def run_stream(self, call: ModelCall, on_delta: Any) -> ModelResult:
        output = self._output(call)
        text = json.dumps(output)
        for start in range(0, len(text), 5):
            on_delta(1, text[start:start + 5])
            time.sleep(0.001)
        return ModelResult(output=output, duration_ms=1, cost_usd=0.0)


class FakeRepo:
    def __init__(self) -> None:
        self.threads: dict[UUID, dict[str, Any]] = {}
        self.messages: dict[UUID, list[dict[str, Any]]] = {}
        self.owners: dict[UUID, UUID] = {}
        self.memory: dict[UUID, MemoryUpdate] = {}
        self.images: dict[UUID, dict[str, Any]] = {}

    async def get_thread(self, _s: Any, user_id: UUID, thread_id: UUID) -> Any:
        return self.threads.get(thread_id) if self.owners.get(thread_id) == user_id else None

    async def create_thread(self, _s: Any, tenant_id: UUID, user_id: UUID, title: str) -> UUID:
        thread_id = uuid4()
        self.owners[thread_id] = user_id
        self.threads[thread_id] = {"id": thread_id, "title": title, "created_at": NOW,
                                   "updated_at": NOW}
        return thread_id

    async def add_exchange(self, _s: Any, _t: UUID, thread_id: UUID, question: str,
                           answer: GroundedAnswer, image_id: UUID | None = None) -> UUID:
        message_id = uuid4()
        stored = repo.stored_citations(answer)  # the real jsonb array shape
        reading = self.images.get(image_id, {}).get("reading") if image_id else None
        self.messages.setdefault(thread_id, []).extend([
            {"id": uuid4(), "role": "user", "content": question, "citations": [],
             "grounding": None, "agent_version": "", "created_at": NOW,
             "image_id": image_id, "image_reading": reading},
            {"id": message_id, "role": "assistant", "content": answer.text,
             "citations": stored, "grounding": answer.grounding,
             "agent_version": answer.agent_version, "created_at": NOW},
        ])
        return message_id

    async def memory_state(self, _s: Any, thread_id: UUID) -> MemoryState:
        saved = self.memory.get(thread_id)
        covered = saved.covered if saved else 0
        turns = tuple(Turn(m["role"], m["content"])
                      for m in self.messages.get(thread_id, [])[covered:])
        return MemoryState(saved.summary if saved else "", covered, turns)

    async def save_memory(self, _s: Any, thread_id: UUID, update: MemoryUpdate) -> None:
        self.memory[thread_id] = update

    async def thread_messages(self, _s: Any, thread_id: UUID) -> list[dict[str, Any]]:
        return self.messages.get(thread_id, [])

    async def list_threads(self, _s: Any, user_id: UUID) -> list[dict[str, Any]]:
        return [{**t, "message_count": len(self.messages.get(t["id"], []))}
                for t in self.threads.values()]

    # tutor_images (apps.api.app.tutor.images)
    async def insert_image(self, _s: Any, tenant_id: UUID, user_id: UUID, image_id: UUID,
                           key: str, image: Any) -> None:
        self.images[image_id] = {"id": image_id, "user_id": user_id, "storage_key": key,
                                 "content_type": image.content_type, "reading": None,
                                 "reading_version": ""}

    async def get_image(self, _s: Any, user_id: UUID, image_id: UUID) -> Any:
        row = self.images.get(image_id)
        return dict(row) if row and row["user_id"] == user_id else None

    async def save_reading(self, _s: Any, image_id: UUID, reading: Any, version: str) -> None:
        self.images[image_id].update(reading=reading.model_dump(mode="json"),
                                     reading_version=version)


def _patch_search(monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]) -> None:
    async def fake_search(_s: Any, user_id: UUID, query: str, _v: Any, limit: int) -> Any:
        state["search"] = (user_id, query, limit)
        return state["hits"]

    async def fake_figures(
        _s: Any, user_id: UUID, query: str, limit: int = 12, query_vector: Any = None
    ) -> Any:
        state["figure_search"] = (user_id, query, limit)
        return state["figures"]

    async def fake_title(_s: Any, user_id: UUID, source_id: UUID) -> str | None:
        return state["sources"].get((user_id, source_id))

    async def fake_page(_s: Any, user_id: UUID, source_id: UUID, page: int, n: int) -> Any:
        state["page_search"] = (user_id, source_id, page)
        return state["page_hits"][:n]

    async def fake_page_figures(_s: Any, _u: UUID, _sid: UUID, _p: int, n: int) -> Any:
        return state["page_figures"][:n]

    async def fake_expand(_s: Any, user_id: UUID, chunk_ids: Any, intent: str) -> Any:
        state["graph_call"] = (user_id, list(chunk_ids), intent)
        return state["graph"]

    monkeypatch.setattr(rerank, "ready", lambda: None)  # no paid reranker in unit tests
    monkeypatch.setattr(graph, "expand", fake_expand)
    monkeypatch.setattr(search, "hybrid_search", fake_search)
    monkeypatch.setattr(search, "search_figures", fake_figures)
    monkeypatch.setattr(search, "source_title", fake_title)
    monkeypatch.setattr(search, "page_chunks", fake_page)
    monkeypatch.setattr(search, "page_figures", fake_page_figures)


@contextmanager
def tutor_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Patch retrieval, persistence, storage, and the transport; yield the mutable state."""
    session, fake_repo, store = FakeSession(), FakeRepo(), MemoryObjectStore()
    state: dict[str, Any] = {"session": session, "repo": fake_repo, "hits": [HIT],
                             "figures": [], "transport": FakeTransport(SOURCE_OK),
                             "store": store, "sources": {}, "page_hits": [],
                             "page_figures": [], "graph": []}
    _patch_search(monkeypatch, state)

    async def fake_set_tenant(_s: Any, tenant_id: UUID) -> None:
        session.events.append(f"tenant:{tenant_id}")

    async def no_vector(_tenant: Any, _query: str) -> None:
        return None

    monkeypatch.setattr(service, "query_vector", no_vector)
    monkeypatch.setattr(service, "set_database_tenant", fake_set_tenant)
    monkeypatch.setattr(tutor_api, "set_database_tenant", fake_set_tenant)
    for name in ("get_thread", "create_thread", "add_exchange", "memory_state",
                 "save_memory", "thread_messages", "list_threads"):
        monkeypatch.setattr(repo, name, getattr(fake_repo, name))
    for name in ("insert_image", "get_image", "save_reading"):
        monkeypatch.setattr(images, name, getattr(fake_repo, name))

    def transport() -> Any:
        if state["transport"] is None:
            return None
        state["transport"].session = session
        return state["transport"]

    app.dependency_overrides[tutor_api.principal_context] = lambda: state.get(
        "principal", PRINCIPAL)
    app.dependency_overrides[tutor_api.tenant_db_session] = lambda: session
    app.dependency_overrides[tutor_api.model_transport] = transport
    app.dependency_overrides[tutor_api.tutor_store] = lambda: store
    try:
        yield state
    finally:
        app.dependency_overrides.clear()
