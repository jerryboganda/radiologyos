"""Pause, quota pause, collect & ask, and the owner's controls (ADR 0037)."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.main import app
from apps.worker.app.ingest import vision
from apps.worker.app.ingest.types import Deferred
from apps.worker.app.knowledge import runtime
from fastapi.testclient import TestClient
from packages.library.figure_context import figure_problem
from packages.library.parse_models import SourceImageCase
from packages.models import gateway
from packages.models.claude_code import ModelResult, OwnerApprovalRequired, UsageLimitError
from packages.models.codex import retry_after
from packages.pipeline import state

HEADERS = {"x-user-id": "10000000-0000-4000-8000-000000000001",
           "x-tenant-id": "20000000-0000-4000-8000-000000000001"}


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.data.get(key, {}))

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.data[key] = dict(mapping)

    def expire(self, key: str, ttl: int) -> None:
        return None


def test_manual_and_quota_pauses_are_shared_and_the_owner_is_told_once() -> None:
    r = FakeRedis()
    assert not state.current(r).paused
    state.set_manual(True, r)
    assert state.current(r).reason == "manual" and state.current(r).recheck_in() == 300
    state.set_manual(False, r)
    until = state.quota_hit("chatgpt", 3600, r)
    assert until is not None and until > time.time() + 3600  # reset time plus a margin
    assert state.quota_hit("chatgpt", 3600, r) is None  # second hit: no second alert
    paused = state.current(r)
    assert (paused.reason, paused.provider) == ("quota", "chatgpt")
    assert 3600 <= paused.recheck_in() <= 3600 + state.QUOTA_MARGIN_S
    state.clear_quota(r)
    assert not state.current(r).paused


def test_unreachable_redis_never_blocks_work() -> None:
    class Down:
        def get(self, _key: str) -> None:
            raise ConnectionError("down")

    assert not state.current(Down()).paused


def test_the_chatgpt_reset_time_is_read_from_the_message() -> None:
    assert retry_after("usage limit. try again in 2 hours 5 minutes.") == 7500
    assert retry_after("please try again in 45 minutes") == 2700
    assert retry_after("rate limit") is None


def _case(**extra: Any) -> SourceImageCase:
    base: dict[str, Any] = {
        "modality": "CT", "anatomy": "brain", "visible_text": "", "findings": ["x"],
        "impression": "SAH", "differentials": [], "teaching_points": [], "topics": [],
        "confidence": "high", "impression_source": "model", "source_quote": ""}
    return SourceImageCase(**{**base, **extra})


def test_figure_gate_asks_sol_to_look_again() -> None:
    context = "[page 3] Diagnosis: subarachnoid haemorrhage"
    assert figure_problem(_case(), context) is None
    assert figure_problem(_case(findings=[], impression=""), context) == "empty_reading"
    assert figure_problem(_case(impression_source="source", source_quote="Diagnosis: SDH"),
                          context) == "unverified_source_quote"
    assert figure_problem(_case(confidence="low"), context) == gateway.soft("low_confidence")


class _Transport:
    backends = ("codex", "claude_code")

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    def run(self, call: Any) -> ModelResult:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return ModelResult(output=self.outcome, duration_ms=1, cost_usd=0.0)


def test_knowledge_calls_stop_on_a_pause_and_report_items_for_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits: list[Any] = []
    monkeypatch.setattr(runtime.pausing, "quota_hit", hits.append)
    monkeypatch.setattr(runtime.pausing, "paused", lambda: True)
    deps = runtime.KnowledgeDeps(engine=None, transport=_Transport({}))  # type: ignore[arg-type]
    with pytest.raises(runtime.Deferred):
        runtime.call_agent_result(deps, "topic_classify", "p")
    monkeypatch.setattr(runtime.pausing, "paused", lambda: False)
    limited = runtime.KnowledgeDeps(None, _Transport(UsageLimitError("q", 60, "chatgpt")))  # type: ignore[arg-type]
    with pytest.raises(runtime.Deferred):
        runtime.call_agent_result(limited, "topic_classify", "p")
    assert [h.provider for h in hits] == ["chatgpt"]
    monkeypatch.setattr(runtime, "run_agent", _raise(OwnerApprovalRequired("x")))
    assert runtime.call_agent_result(deps, "topic_classify", "p") == (None, runtime.NO_ANSWER)


def _raise(exc: Exception) -> Any:
    def run(*_a: Any, **_k: Any) -> Any:
        raise exc
    return run


async def test_pages_stop_between_units_when_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, frozenset[str]]] = []

    class Tx:
        async def __aenter__(self) -> Tx:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

    async def approved(_s: Any, _src: Any, agent: str) -> set[str]:
        return {"page:2"} if agent == "image_case" else set()

    async def parse(_d: Any, _j: Any, _s: Any, page: dict[str, Any]) -> None:
        seen.append((page["page_no"], gateway._approved.get()))
        if page["page_no"] == 2:
            monkeypatch.setattr(vision.pausing, "paused", lambda: True)

    done: list[str] = []

    async def mark_done(_s: Any, _src: Any, agent: str, unit: str) -> None:
        done.append(f"{agent}:{unit}")

    monkeypatch.setattr(vision.db, "tenant_tx", lambda *_a: Tx())
    monkeypatch.setattr(vision.escalations, "approved_units", approved)
    monkeypatch.setattr(vision.escalations, "mark_done", mark_done)
    monkeypatch.setattr(vision, "parse_page", parse)
    monkeypatch.setattr(vision.pausing, "paused", lambda: False)
    job = {"tenant_id": UUID(int=1), "entity_id": UUID(int=2)}
    with pytest.raises(Deferred):
        deps = type("D", (), {"engine": None})()
        await vision.parse_pages(deps, job, {}, [{"page_no": n} for n in (1, 2, 3)])
    # Page 3 never started; only page 2's approved figure agent ran on the gated target.
    assert seen == [(1, frozenset()), (2, frozenset({"image_case"}))]
    assert done == ["image_case:page:2"]


def test_pipeline_controls_are_admin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app.api import admin_pipeline

    client = TestClient(app)
    assert client.post("/v1/admin/pipeline/pause").status_code == 401
    app.dependency_overrides[admin_pipeline.tenant_db_session] = lambda: object()
    try:
        for method, path in (("get", ""), ("post", "/pause"), ("post", "/approve")):
            response = getattr(client, method)(f"/v1/admin/pipeline{path}", headers=HEADERS)
            assert response.status_code == 403, path
    finally:
        app.dependency_overrides.clear()


def test_admin_pause_resume_and_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app.api import admin_pipeline

    r, sent = FakeRedis(), []
    monkeypatch.setattr(state, "_client", lambda: r)
    monkeypatch.setattr(admin_pipeline, "_send", lambda name, *_a: sent.append(name))
    admin = {**HEADERS, "x-role": "org_admin"}
    app.dependency_overrides[admin_pipeline.tenant_db_session] = lambda: object()
    try:
        client = TestClient(app)
        assert client.post("/v1/admin/pipeline/pause", headers=admin).status_code == 204
        assert state.current(r).reason == "manual"
        assert client.post("/v1/admin/pipeline/resume", headers=admin).status_code == 204
        assert not state.current(r).paused
        assert client.post("/v1/admin/pipeline/approve", headers=admin).status_code == 202
    finally:
        app.dependency_overrides.clear()
    assert sent == ["radbrain.approve_escalations"]


def test_escalation_migration_is_expand_only_with_forced_rls() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    source = (root / "apps/api/migrations/versions/20260926_0106_owner_escalations.py").read_text(
        encoding="utf-8")
    upgrade = source.split("def downgrade")[0]
    assert "DROP COLUMN" not in upgrade and "RENAME" not in upgrade
    assert "FORCE ROW LEVEL SECURITY" in upgrade and "model_escalations_tenant_all" in upgrade
    assert 'down_revision = "20260926_0105"' in source
