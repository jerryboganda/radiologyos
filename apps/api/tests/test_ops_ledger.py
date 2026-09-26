"""Model-call ledger (ADR 0032): one record per attempt, no content, safe recorders."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from apps.worker.app.ops import llm_ledger
from packages.models import ledger
from packages.models.claude_code import ModelCall, ModelCallError, ModelResult, UsageLimitError
from packages.models.claude_stream import StreamUnsupported
from packages.models.gateway import build_calls, load_agent, run_agent
from packages.observability import trace

TENANT = UUID("20000000-0000-4000-8000-000000000001")
USER = UUID("10000000-0000-4000-8000-000000000001")
REQUEST = "30000000-0000-4000-8000-000000000003"
VALID_PAGE = {"page_type": "text", "blocks": [], "figures": [], "topics": []}
SECRET_PROMPT = "synthetic private page text that must never be recorded"


class Sequenced:
    """Serves every backend; returns (or raises) the queued outcomes in order."""

    def __init__(self, *outcomes: Any, usage: dict[str, Any] | None = None) -> None:
        self.outcomes = list(outcomes)
        self.usage = usage or {"input_tokens": 100, "cache_read_input_tokens": 20,
                               "output_tokens": 30}
        self.backends = tuple({c.backend for c in build_calls(load_agent("page_parse"), "p")})

    def run(self, call: ModelCall) -> ModelResult:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ModelResult(output=outcome, duration_ms=5, cost_usd=0.25, usage=self.usage,
                           backend=call.backend)


@pytest.fixture(autouse=True)
def owner_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    """These cases exercise every target, including the approval-gated last one."""
    monkeypatch.setenv("BULK_CLAUDE_FALLBACK_APPROVED", "true")


@pytest.fixture
def records() -> Iterator[list[ledger.CallRecord]]:
    seen: list[ledger.CallRecord] = []
    ledger.add_recorder(seen.append)
    try:
        with trace.bound(REQUEST, TENANT, USER):
            yield seen
    finally:
        ledger.remove_recorder(seen.append)


def _targets() -> int:
    count = len(build_calls(load_agent("page_parse"), "p"))
    if count < 2:
        pytest.skip("page_parse needs two targets for the fallback cases")
    return count


def test_success_records_ids_numbers_and_identity_only(records: list[ledger.CallRecord]) -> None:
    run_agent(Sequenced(VALID_PAGE), "page_parse", SECRET_PROMPT)
    [rec] = records
    assert (rec.status, rec.agent, rec.route) == ("ok", load_agent("page_parse").key, "vision")
    assert (rec.tenant_id, rec.user_id, rec.request_id) == (TENANT, USER, REQUEST)
    assert (rec.input_tokens, rec.output_tokens, rec.cost_usd) == (120, 30, 0.25)
    assert SECRET_PROMPT not in repr(rec)


def test_every_failed_attempt_is_recorded_with_its_outcome(
    records: list[ledger.CallRecord],
) -> None:
    n = _targets()
    failures: list[Any] = [UsageLimitError("q"), ModelCallError("boom"), {"not": "a page"}]
    outcomes = failures[: n - 1] + [VALID_PAGE]
    run_agent(Sequenced(*outcomes), "page_parse", "p")
    expected = [("usage_limit", "UsageLimitError"), ("error", "ModelCallError"),
                ("error", "schema_invalid")][: n - 1] + [("ok", None)]
    assert [(r.status, r.error_code) for r in records] == expected
    assert records[0].input_tokens is None  # no result, no numbers


def test_quality_gate_rejection_is_recorded_per_attempt(
    records: list[ledger.CallRecord],
) -> None:
    n = _targets()
    run_agent(Sequenced(*[VALID_PAGE] * n), "page_parse", "p", accept=lambda _: "low")
    statuses = [(r.status, r.error_code) for r in records]
    assert statuses == [("rejected", "quality_gate")] * (n - 1) + [("ok", "gate_kept_last")]


def test_exhausted_targets_raise_after_recording_each(records: list[ledger.CallRecord]) -> None:
    n = _targets()
    with pytest.raises(UsageLimitError):
        run_agent(Sequenced(*[UsageLimitError("q")] * n), "page_parse", "p")
    assert [r.status for r in records] == ["usage_limit"] * n


class Streaming(Sequenced):
    def __init__(self, stream_outcome: Any, *outcomes: Any) -> None:
        super().__init__(*outcomes)
        self.stream_outcome = stream_outcome

    def run_stream(self, call: ModelCall, on_delta: Any) -> ModelResult:
        if isinstance(self.stream_outcome, Exception):
            raise self.stream_outcome
        return ModelResult(output=self.stream_outcome, duration_ms=5, cost_usd=0.0,
                           backend=call.backend)


def test_streamed_attempts_are_recorded_but_unsupported_streams_are_not(
    records: list[ledger.CallRecord],
) -> None:
    run_agent(Streaming(VALID_PAGE), "page_parse", "p", on_delta=lambda _: None)
    assert [r.status for r in records] == ["ok"]
    records.clear()
    run_agent(Streaming(StreamUnsupported("x"), VALID_PAGE), "page_parse", "p",
              on_delta=lambda _: None)
    assert [r.status for r in records] == ["ok"]  # only the plain call ran a model
    records.clear()
    run_agent(Streaming({"bad": 1}, VALID_PAGE), "page_parse", "p", on_delta=lambda _: None)
    assert [(r.status, r.error_code) for r in records] == [("error", "schema_invalid"),
                                                           ("ok", None)]
    records.clear()
    with pytest.raises(UsageLimitError):
        run_agent(Streaming(UsageLimitError("q")), "page_parse", "p", on_delta=lambda _: None)
    assert [r.status for r in records] == ["usage_limit"]


def test_a_failing_recorder_never_breaks_the_call(records: list[ledger.CallRecord]) -> None:
    def broken(_: ledger.CallRecord) -> None:
        raise RuntimeError("sink down")

    ledger.add_recorder(broken)
    try:
        parsed, _ = run_agent(Sequenced(VALID_PAGE), "page_parse", "p")
    finally:
        ledger.remove_recorder(broken)
    assert parsed is not None and len(records) == 1


def test_token_counts_are_parsed_defensively() -> None:
    assert ledger.token_counts({"prompt_tokens": 7, "completion_tokens": 3}) == (7, 3)
    assert ledger.token_counts({"input_tokens": "x", "output_tokens": -1}) == (None, None)
    assert ledger.token_counts(None) == (None, None)
    assert ledger.token_counts({"input_tokens": True}) == (None, None)


class FakeSession:
    def __init__(self, recent: int = 0, created: bool = True) -> None:
        self.recent, self.created = recent, created
        self.sql: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)
        self.sql.append((sql, params or {}))
        session = self

        class Result:
            def scalar_one(self) -> int:
                return session.recent

            def scalar_one_or_none(self) -> Any:
                return "alert-id" if session.created else None

        return Result()


def _record(**kw: Any) -> ledger.CallRecord:
    base = dict(agent="tutor_answer/v3", route="reason", backend="claude_code",
                model="claude-opus-5-5", effort="high", status="ok", duration_ms=10,
                tenant_id=TENANT, user_id=USER, request_id=REQUEST)
    return ledger.CallRecord(**{**base, **kw})


def test_insert_writes_ids_and_numbers_only() -> None:
    session = FakeSession()
    asyncio.run(llm_ledger.insert_call(session, _record(request_id="not-a-uuid")))  # type: ignore[arg-type]
    sql, params = session.sql[0]
    assert "INSERT INTO llm_calls" in sql and params["rid"] is None
    assert set(params) == {"t", "u", "rid", "agent", "route", "backend", "model", "effort",
                           "status", "code", "ms", "tin", "tout", "cost"}


def test_spike_alert_needs_more_than_the_threshold() -> None:
    quiet, busy = FakeSession(recent=5), FakeSession(recent=6)
    assert asyncio.run(llm_ledger.raise_spike_alert(quiet, TENANT, 5)) is False  # type: ignore[arg-type]
    assert asyncio.run(llm_ledger.raise_spike_alert(busy, TENANT, 5)) is True  # type: ignore[arg-type]
    upsert = busy.sql[-1][0]
    assert "model_usage_limit" in upsert and "acknowledged_at < now() - interval '1 hour'" in upsert


def test_sink_queues_records_and_skips_tenantless_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[ledger.CallRecord] = []
    real_store = llm_ledger.store

    async def fake_store(engine: Any, record: ledger.CallRecord, threshold: int) -> None:
        stored.append(record)

    monkeypatch.setattr(llm_ledger, "store", fake_store)
    monkeypatch.setattr(llm_ledger, "create_async_engine", lambda *a, **k: _Engine())
    sink = llm_ledger.LedgerSink("postgresql+asyncpg://synthetic/none")
    sink(_record())
    sink(_record(status="usage_limit"))
    sink.flush(5.0)
    assert [r.status for r in stored] == ["ok", "usage_limit"]
    # Without a tenant there is no RLS context to write in: nothing is stored.
    assert asyncio.run(real_store(_Engine(), _record(tenant_id=None), 5)) is None  # type: ignore[arg-type]


class _Engine:
    async def dispose(self) -> None:
        return None


def test_threshold_is_configurable_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_USAGE_LIMIT_ALERT_PER_HOUR", "9")
    assert llm_ledger.alert_threshold() == 9
    monkeypatch.setenv("MODEL_USAGE_LIMIT_ALERT_PER_HOUR", "lots")
    assert llm_ledger.alert_threshold() == 5
