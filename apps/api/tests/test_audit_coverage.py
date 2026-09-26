"""Every successful mutating request leaves an audit row with ids only (ADR 0032, G23)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.api import study
from apps.api.app.main import app
from apps.api.app.ops import audit
from apps.api.app.security.principal import Principal
from apps.api.tests.study_fakes import MemoryStudyRepo
from fastapi.testclient import TestClient
from packages.observability import trace

USER = UUID("10000000-0000-4000-8000-000000000001")
TENANT = UUID("20000000-0000-4000-8000-000000000001")
HEADERS = {"x-user-id": str(USER), "x-tenant-id": str(TENANT)}
REQUEST = "30000000-0000-4000-8000-000000000003"
NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)
Row = tuple[audit.Mutation, UUID | None]


@pytest.fixture
def rows() -> Iterator[list[Row]]:
    captured: list[Row] = []

    async def capture(mutation: audit.Mutation, request_id: UUID | None) -> None:
        captured.append((mutation, request_id))

    memory = MemoryStudyRepo()
    audit.set_writer(capture)
    app.dependency_overrides[study.get_repo] = lambda: memory
    app.dependency_overrides[study.get_now] = lambda: NOW
    app.state.audit_repo = memory
    yield captured
    app.dependency_overrides.clear()
    audit.set_writer(None)


def _profile() -> dict[str, Any]:
    return {"exam_date": (NOW.date() + timedelta(days=120)).isoformat(),
            "exam_targets": ["fcps2_theory"], "daily_minutes": 90, "timezone": "Asia/Karachi"}


def test_representative_mutations_write_one_row_each(rows: list[Row]) -> None:
    client = TestClient(app)
    repo: MemoryStudyRepo = app.state.audit_repo
    headers = {**HEADERS, "x-request-id": REQUEST}
    assert client.put("/v1/study/profile", json=_profile(), headers=headers).status_code == 200
    chunk = repo.add_chunk(USER)
    created = client.post("/v1/study/cards", headers=HEADERS, json={
        "chunk_id": str(chunk), "curriculum_code": "CHEST", "topic": "synthetic topic",
        "front": "Synthetic front?", "back": "Synthetic back."})
    assert created.status_code == 201
    card_id = created.json()["id"]
    reviewed = client.post(f"/v1/study/cards/{card_id}/review", json={"rating": 3},
                           headers=HEADERS)
    assert reviewed.status_code == 200
    assert [(m.action, m.target(), m.route) for m, _ in rows] == [
        ("api.put", ("study", None), "/v1/study/profile"),
        ("api.post", ("study", None), "/v1/study/cards"),
        ("api.post", ("card", card_id), "/v1/study/cards/{card_id}/review"),
    ]
    assert all((m.tenant_id, m.user_id) == (TENANT, USER) for m, _ in rows)
    assert rows[0][1] == UUID(REQUEST)
    assert "Synthetic front" not in repr(rows)  # bodies never reach the audit row


def test_reads_failures_and_anonymous_requests_are_not_audited(rows: list[Row]) -> None:
    client = TestClient(app)
    client.get("/v1/study/profile", headers=HEADERS)
    bad = client.put("/v1/study/profile", json={**_profile(), "daily_minutes": 1},
                     headers=HEADERS)
    assert bad.status_code == 422
    assert client.put("/v1/study/profile", json=_profile()).status_code == 401
    assert rows == []


def test_overridden_principals_have_no_identity_to_audit(rows: list[Row]) -> None:
    app.dependency_overrides[study.principal_context] = lambda: Principal(USER, TENANT)
    assert TestClient(app).put("/v1/study/profile", json=_profile()).status_code == 200
    assert rows == []


def test_every_mutating_route_is_covered_or_explicitly_exempt() -> None:
    uncovered = []
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            verb = method.upper()
            if verb not in audit.MUTATING:
                continue
            exempt = path in audit.READ_ONLY_POSTS or path.startswith(audit.EXEMPT_PREFIXES)
            if not exempt and not audit.should_audit(verb, path, 200):
                uncovered.append((verb, path))
    assert uncovered == []
    assert audit.should_audit("POST", "/v1/library/search", 200) is False
    assert audit.should_audit("POST", "/v1/preview/sources", 200) is False
    assert audit.should_audit("DELETE", "/v1/library/sources/{source_id}", 204) is True


def test_a_named_event_replaces_the_generic_row() -> None:
    written: list[Row] = []

    async def capture(mutation: audit.Mutation, request_id: UUID | None) -> None:
        written.append((mutation, request_id))

    audit.set_writer(capture)
    try:
        mutation = audit.Mutation(TENANT, USER, "DELETE", "/v1/library/sources/{source_id}",
                                  204, {"source_id": "s-1"})
        scope = audit.AuditScope(named_events=1)
        assert asyncio.run(audit.request_audit(mutation, scope)) is False
        assert asyncio.run(audit.request_audit(mutation, audit.AuditScope())) is True
    finally:
        audit.set_writer(None)
    assert written[0][0].target() == ("source", "s-1")


def test_named_audit_events_carry_the_request_id() -> None:
    class Session:
        params: dict[str, Any] = {}

        async def execute(self, _: Any, params: dict[str, Any]) -> None:
            Session.params = params

    scope = audit.open_scope()
    with trace.bound(request_id=REQUEST):
        asyncio.run(audit.audit(Session(), Principal(USER, TENANT), "source.uploaded",  # type: ignore[arg-type]
                                "source", "s-1", {"bytes": 3}))
    assert Session.params["rid"] == UUID(REQUEST) and scope.named_events == 1
    assert json.loads(Session.params["m"]) == {"bytes": 3}


def test_a_failing_generic_write_never_fails_the_request() -> None:
    async def broken(*_: Any) -> None:
        raise ConnectionError("db down")

    audit.set_writer(broken)
    try:
        mutation = audit.Mutation(TENANT, USER, "POST", "/v1/study/cards", 201, {})
        assert asyncio.run(audit.request_audit(mutation, None)) is False
    finally:
        audit.set_writer(None)
