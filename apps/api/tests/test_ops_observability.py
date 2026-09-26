"""Request ids, trace propagation, /metrics guard, readiness detail (ADR 0032)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import ops
from apps.api.app.core.config import get_settings
from apps.api.app.main import app
from apps.worker.app.ingest import db as ingest_db
from apps.worker.app.ops import worker_signals
from fastapi.testclient import TestClient
from packages.observability import metrics, trace

client = TestClient(app)
TENANT = "20000000-0000-4000-8000-000000000002"
USER = "10000000-0000-4000-8000-000000000001"
HEADERS = {"x-user-id": USER, "x-tenant-id": TENANT}


class MemoryShared(metrics.SharedCounters):
    def __init__(self) -> None:
        super().__init__(lambda: None)
        self.values: dict[str, dict[str, float]] = {}

    def inc(self, metric: str, labels: Any, amount: float = 1.0) -> None:
        field = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        bucket = self.values.setdefault(metric, {})
        bucket[field] = bucket.get(field, 0.0) + amount

    def read(self, metric: str) -> dict[str, float]:
        return dict(self.values.get(metric, {}))


@pytest.fixture
def shared() -> Iterator[MemoryShared]:
    memory = MemoryShared()
    metrics.set_shared(memory)
    yield memory
    metrics.set_shared(None)


def test_request_id_is_kept_when_valid_and_replaced_when_not() -> None:
    kept = client.get("/health/live", headers={"x-request-id": USER})
    assert kept.headers["x-request-id"] == USER
    replaced = client.get("/health/live", headers={"x-request-id": "<script>"})
    assert UUID(replaced.headers["x-request-id"]) and "<" not in replaced.headers["x-request-id"]


def test_metrics_refuses_external_callers() -> None:
    assert ops.metrics_allowed("127.0.0.1", {}, "") is True
    assert ops.metrics_allowed("172.18.0.5", {}, "") is True
    assert ops.metrics_allowed("8.8.8.8", {}, "") is False
    assert ops.metrics_allowed("127.0.0.1", {"x-forwarded-for": "8.8.8.8"}, "") is False
    assert ops.metrics_allowed("testclient", {}, "") is False
    assert ops.metrics_allowed("127.0.0.1", {}, "s3cret-token") is False
    assert ops.metrics_allowed("8.8.8.8", {"authorization": "Bearer s3cret-token"},
                               "s3cret-token") is True
    assert client.get("/metrics").status_code == 404  # TestClient is not an internal IP


def test_metrics_exposes_requests_jobs_and_model_calls(
    monkeypatch: pytest.MonkeyPatch, shared: MemoryShared
) -> None:
    monkeypatch.setattr(get_settings(), "metrics_token", "synthetic-metrics-token")
    shared.inc("radbrain_job_steps_total", {"step": "render", "status": "succeeded"})
    shared.inc("radbrain_model_calls_total", {"agent": "page_parse/v2", "backend": "claude_code",
                                              "status": "usage_limit"})
    client.get("/health/live")
    response = client.get("/metrics", headers={"authorization": "Bearer synthetic-metrics-token"})
    assert response.status_code == 200
    body = response.text
    assert 'radbrain_http_requests_total{method="GET",route="/health/live",status="200"}' in body
    bucket = 'radbrain_http_request_seconds_bucket{method="GET",route="/health/live",le="+Inf"}'
    assert bucket in body
    assert 'radbrain_job_steps_total{status="succeeded",step="render"} 1' in body
    assert 'status="usage_limit"' in body
    assert TENANT not in body and USER not in body


def test_readiness_names_each_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(*_: Any) -> str:
        return "ok"

    async def down(*_: Any) -> str:
        return "unavailable"

    monkeypatch.setattr(ops, "_database", ok)
    monkeypatch.setattr(ops, "_redis", down)
    monkeypatch.setattr(ops, "_object_storage", lambda _: "ok")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "unavailable",
                                         "object_storage": "ok"}
    monkeypatch.setattr(ops, "_redis", ok)
    assert client.get("/health/ready").json()["status"] == "ready"


def test_histogram_and_counter_render_prometheus_text() -> None:
    counter = metrics.Counter("t_total", "help", ("a",))
    counter.inc('x"y')
    hist = metrics.Histogram("t_seconds", "help", ("a",), buckets=(1.0,))
    hist.observe(0.5, "x")
    hist.observe(2.0, "x")
    text = "\n".join([*counter.render(), *hist.render()])
    assert 't_total{a="x\\"y"} 1' in text
    assert 't_seconds_bucket{a="x",le="1"} 1' in text
    assert 't_seconds_bucket{a="x",le="+Inf"} 2' in text and 't_seconds_count{a="x"} 2' in text


def test_shared_counters_fail_open_and_log_once(caplog: pytest.LogCaptureFixture) -> None:
    class Down:
        def hincrbyfloat(self, *_: Any) -> None:
            raise ConnectionError("redis down")

    counters = metrics.SharedCounters(Down, cooldown_s=0.0)
    with caplog.at_level(logging.WARNING, logger="radbrain.metrics"):
        counters.inc("m", {"a": "b"})
        counters.inc("m", {"a": "b"})
    assert sum("shared_metrics_unavailable" in r.getMessage() for r in caplog.records) == 1


def test_job_step_outcomes_are_counted(shared: MemoryShared) -> None:
    class Session:
        async def execute(self, *_: Any) -> None:
            return None

    job = {"tenant_id": TENANT, "id": USER, "entity_id": USER, "pipeline_version": 1}
    asyncio.run(ingest_db.mark_step(Session(), job, "chunk", "running"))  # type: ignore[arg-type]
    asyncio.run(ingest_db.mark_step(Session(), job, "chunk", "succeeded"))  # type: ignore[arg-type]
    assert shared.read("radbrain_job_steps_total") == {"status=succeeded,step=chunk": 1.0}


def test_celery_tasks_carry_request_and_tenant_ids() -> None:
    headers: dict[str, Any] = {}
    with trace.bound(request_id=USER):
        worker_signals.add_request_header(headers=headers)
    assert headers == {"radbrain_request_id": USER}

    class Request:
        radbrain_request_id = USER

    class Task:
        request = Request()

    worker_signals.bind_task(task_id="task-1", task=Task(), args=[TENANT, "job"], kwargs={})
    ctx = trace.current()
    assert (ctx.task_id, str(ctx.tenant_id), ctx.request_id) == ("task-1", TENANT, USER)
    record = logging.LogRecord("radbrain.worker", logging.INFO, __file__, 1, "x", (), None)
    worker_signals.TraceFilter().filter(record)
    assert (record.trace_task, record.trace_tenant) == ("task-1", TENANT)  # type: ignore[attr-defined]
    worker_signals.unbind_task()
    assert trace.current().task_id is None
    worker_signals.bind_task(task_id="beat", task=None, args=[], kwargs={})
    assert trace.current().tenant_id is None  # beat tasks act for no tenant
    worker_signals.unbind_task()


def test_request_log_carries_route_template_and_tenant(caplog: pytest.LogCaptureFixture) -> None:
    from apps.api.app.observability import RedactingJsonFormatter

    records: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Grab()
    logger = logging.getLogger("radbrain.api")
    logger.addHandler(handler)
    try:
        # A refused switch resolves the principal; the directory is never read.
        from apps.api.app.api import account

        app.dependency_overrides[account.get_directory] = lambda: None
        client.post(f"/v1/tenants/switch?tenant_id={uuid4()}", headers=HEADERS)
    finally:
        app.dependency_overrides.pop(account.get_directory, None)
        logger.removeHandler(handler)
    line = RedactingJsonFormatter().format(records[-1])
    assert '"path":"/v1/tenants/switch"' in line and f'"tenant_id":"{TENANT}"' in line
    assert '"duration_ms"' in line
