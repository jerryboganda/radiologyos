"""The owner's red review list (owner rule, ADR 0038)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.main import app
from apps.worker.app.ingest import vision
from fastapi.testclient import TestClient
from packages.models import gateway
from packages.models.claude_code import ModelCallError, ModelResult

HEADERS = {"x-user-id": "10000000-0000-4000-8000-000000000001",
           "x-tenant-id": "20000000-0000-4000-8000-000000000001"}
SOURCE = UUID(int=7)
CHUNK_TEXT = "Horseshoe kidney: fused lower poles"


class _Result:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int = 0) -> None:
        self.rows, self.rowcount = rows, rowcount

    def mappings(self) -> list[dict[str, Any]]:
        return self.rows

    def __iter__(self) -> Any:
        return iter(type("Row", (), r) for r in self.rows)


class _Session:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        now = datetime(2026, 9, 27, tzinfo=UTC)
        if "FROM model_escalations" in sql:
            unit = "chunk:" + hashlib.sha256(CHUNK_TEXT.encode()).hexdigest()[:32]
            return _Result([
                {"id": UUID(int=1), "source_id": SOURCE, "source_title": "IMM deck",
                 "agent": "image_case", "unit": "page:12", "reason": "empty_reading",
                 "created_at": now},
                {"id": UUID(int=2), "source_id": SOURCE, "source_title": "IMM deck",
                 "agent": "knowledge_extract", "unit": unit, "reason": "unsupported_claims",
                 "created_at": now}])
        if "FROM chunks" in sql:
            return _Result([{"text": CHUNK_TEXT, "page_from": 14, "page_to": 15}])
        if "FROM claims" in sql:
            return _Result([{"id": UUID(int=3), "statement": "Fat pad sign: medial neck fracture",
                             "doubt": "usually radial head/neck", "evidence_span": "medial neck",
                             "source_id": SOURCE, "source_title": "IMM deck",
                             "page_from": 15, "page_to": 15}])
        self.updates.append(params)
        return _Result([], rowcount=1 if params.get("id") == UUID(int=1) or
                       params.get("st") else 0)


def _client(session: _Session) -> TestClient:
    from apps.api.app.api import red_list

    app.dependency_overrides[red_list.tenant_db_session] = lambda: session
    return TestClient(app)


def test_the_red_list_needs_sign_in_and_shows_items_with_their_pages() -> None:
    assert TestClient(app).get("/v1/library/red-list").status_code == 401
    try:
        body = _client(_Session()).get("/v1/library/red-list", headers=HEADERS).json()
    finally:
        app.dependency_overrides.clear()
    figure, notes = body["items"]
    assert (figure["kind"], figure["page_from"]) == ("figure", 12)
    assert figure["reason"] == "empty_reading"
    assert (notes["kind"], notes["page_from"], notes["page_to"]) == ("notes", 14, 15)
    assert body["flagged_facts"][0]["doubt"] == "usually radial head/neck"


def test_items_are_marked_reviewed_and_facts_kept_or_rejected() -> None:
    session = _Session()
    try:
        client = _client(session)
        assert client.post(f"/v1/library/red-list/{UUID(int=1)}/reviewed",
                           headers=HEADERS).status_code == 204
        assert client.post(f"/v1/library/red-list/{UUID(int=9)}/reviewed",
                           headers=HEADERS).status_code == 404  # not on your list
        assert client.post(f"/v1/library/red-list/claims/{UUID(int=3)}", headers=HEADERS,
                           json={"decision": "reject"}).status_code == 204
        assert client.post(f"/v1/library/red-list/claims/{UUID(int=3)}", headers=HEADERS,
                           json={"decision": "maybe"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
    assert session.updates[-1]["st"] == "rejected"


class _Transport:
    backends = ("codex", "claude_code")

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    def run(self, call: Any) -> ModelResult:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return ModelResult(output=self.outcome, duration_ms=1, cost_usd=0.0)


PAGE = {"page_type": "text", "blocks": [], "figures": [], "topics": []}


async def test_a_kept_answer_short_of_the_bar_and_a_total_failure_go_on_the_red_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BULK_CLAUDE_FALLBACK_APPROVED", "true")
    red: list[tuple[str, str]] = []

    async def flag(_e: Any, _t: Any, _s: Any, agent: str, unit: str, reason: str) -> None:
        red.append((unit, reason))

    monkeypatch.setattr(vision.escalations, "flag_review", flag)
    job = {"tenant_id": UUID(int=1), "entity_id": SOURCE}
    deps: Any = type("D", (), {"engine": None, "transport": _Transport(PAGE)})()
    parsed = await vision._model(deps, job, "page_parse", "page:3", "p",
                                 accept=lambda _: "low_text_coverage")
    assert parsed is not None and red == [("page:3", "low_text_coverage")]
    deps.transport = _Transport(ModelCallError("down"))
    assert await vision._model(deps, job, "page_parse", "page:4", "p") is None
    assert red[-1] == ("page:4", "all_models_failed")


def test_only_the_last_targets_kept_answer_counts_as_short() -> None:
    transport = _Transport(PAGE)
    _, result = gateway.run_agent(transport, "page_parse", "p", accept=lambda _: "low")
    assert result.shortfall is None  # Opus not approved here: it waits for the owner instead
    assert result.escalation == "low"
