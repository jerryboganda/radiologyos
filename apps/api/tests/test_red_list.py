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


NOW = datetime(2026, 9, 27, tzinfo=UTC)
UNIT = "chunk:" + hashlib.sha256(CHUNK_TEXT.encode()).hexdigest()[:32]
BASE = {"source_id": SOURCE, "source_title": "IMM deck", "file_name": "imm-deck.pdf",
        "status": "review", "owner_verdict": None, "owner_note": None, "created_at": NOW,
        "resolved_at": None}


class _Session:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        if "GROUP BY 1, 2, 3, 4, 5, 6" in sql:
            row = {"source_id": SOURCE, "title": "IMM deck", "file_name": "imm-deck.pdf"}
            return _Result([{**row, "agent": "image_case", "reason": "empty_reading",
                             "status": "review", "n": 3},
                            {**row, "agent": "page_parse", "reason": "x", "status": "reviewed",
                             "n": 2},
                            {**row, "agent": "knowledge_extract", "reason": "unsupported_claims",
                             "status": "review", "n": 5},
                            {**row, "agent": "page_parse", "reason": "low_text_coverage",
                             "status": "review", "n": 1}])
        if "GROUP BY 1, 2, 3, 4" in sql:
            return _Result([{"source_id": SOURCE, "title": "IMM deck",
                             "file_name": "imm-deck.pdf", "open": True, "n": 4}])
        if "FROM model_escalations e JOIN" in sql:
            return _Result([
                {**BASE, "id": UUID(int=1), "agent": "image_case", "unit": "page:12",
                 "reason": "empty_reading"},
                {**BASE, "id": UUID(int=2), "agent": "knowledge_extract", "unit": UNIT,
                 "reason": "unsupported_claims"},
                {**BASE, "id": UUID(int=4), "agent": "page_parse", "unit": "page:9",
                 "reason": "low_text_coverage"}])
        if "FROM source_pages p" in sql:
            return _Result([{"source_id": SOURCE, "page_no": 9, "own_text": "own words",
                             "vision_status": "done", "reading": "read words"},
                            {"source_id": SOURCE, "page_no": 12, "own_text": None,
                             "vision_status": "done", "reading": None}])
        if "FROM figures f" in sql:
            return _Result([{"id": UUID(int=5), "source_id": SOURCE, "page_no": 12,
                             "figure_no": 1, "caption": "Fig 1", "description": "renal mass",
                             "modality": "CT", "anatomy": "kidney",
                             "findings": ["exophytic"], "source_quote": None,
                             "impression_origin": None, "has_image": True}])
        if "FROM chunks c WHERE" in sql:
            return _Result([{"id": UUID(int=6), "source_id": SOURCE, "heading": "Kidney",
                             "text": CHUNK_TEXT, "page_from": 14, "page_to": 15,
                             "unit": UNIT}])
        if "SELECT chunk_id" in sql:
            return _Result([{"chunk_id": UUID(int=6), "statement": "Horseshoe kidney fuses",
                             "evidence_span": "fused lower poles", "status": "active"}])
        if "FROM claims c JOIN" in sql:
            return _Result([{"id": UUID(int=3), "statement": "Fat pad sign: medial neck fracture",
                             "doubt": "usually radial head/neck", "evidence_span": "medial neck",
                             "source_id": SOURCE, "source_title": "IMM deck",
                             "file_name": "imm-deck.pdf", "page_from": 15, "page_to": 15,
                             "status": "flagged", "owner_note": None, "owner_decided_at": None,
                             "section_heading": "Elbow", "section_text": "the medial neck"}])
        self.updates.append(params)
        return _Result([], rowcount=1 if params.get("id") == UUID(int=1) or
                       params.get("st") else 0)


def _client(session: _Session) -> TestClient:
    from apps.api.app.api import red_list

    app.dependency_overrides[red_list.tenant_db_session] = lambda: session
    return TestClient(app)


def test_the_red_list_needs_sign_in_and_shows_every_item_with_its_evidence() -> None:
    assert TestClient(app).get("/v1/library/red-list").status_code == 401
    try:
        body = _client(_Session()).get("/v1/library/red-list", headers=HEADERS).json()
    finally:
        app.dependency_overrides.clear()
    page, figure, notes = body["items"]  # ordered by file, then page
    assert (page["kind"], page["page_from"], page["file_name"]) == ("page", 9, "imm-deck.pdf")
    assert (page["own_text"], page["reading"]) == ("own words", "read words")
    assert figure["figures"][0]["description"] == "renal mass"
    assert (notes["page_from"], notes["page_to"], notes["section_text"]) == (14, 15, CHUNK_TEXT)
    assert notes["statements"][0]["evidence_span"] == "fused lower poles"
    fact = body["flagged_facts"][0]
    assert (fact["doubt"], fact["section_text"]) == ("usually radial head/neck", "the medial neck")


def test_the_summary_counts_open_and_reviewed_work_per_file() -> None:
    try:
        body = _client(_Session()).get("/v1/library/red-list/summary", headers=HEADERS).json()
    finally:
        app.dependency_overrides.clear()
    assert body == [{"source_id": str(SOURCE), "source_title": "IMM deck",
                     "file_name": "imm-deck.pdf", "open_pages": 1, "open_figures": 3,
                     "open_notes": 5, "open_facts": 4, "reviewed": 2,
                     "reasons": {"empty_reading": 3, "unsupported_claims": 5,
                                 "low_text_coverage": 1}}]


def test_verdicts_notes_and_fact_decisions_are_saved() -> None:
    session = _Session()
    try:
        client = _client(session)
        assert client.post(f"/v1/library/red-list/{UUID(int=1)}/verdict", headers=HEADERS,
                           json={"verdict": "needs_fix", "note": " wrong organ "}
                           ).status_code == 204
        assert session.updates[-1]["v"] == "needs_fix"
        assert session.updates[-1]["note"] == "wrong organ"
        assert client.post(f"/v1/library/red-list/{UUID(int=9)}/verdict", headers=HEADERS,
                           json={"verdict": "correct"}).status_code == 404  # not yours
        assert client.post(f"/v1/library/red-list/{UUID(int=1)}/verdict", headers=HEADERS,
                           json={"verdict": "maybe"}).status_code == 422
        assert client.post(f"/v1/library/red-list/{UUID(int=1)}/reviewed",
                           headers=HEADERS).status_code == 204
        assert client.post(f"/v1/library/red-list/claims/{UUID(int=3)}", headers=HEADERS,
                           json={"decision": "reject", "note": "old teaching"}
                           ).status_code == 204
        assert session.updates[-1]["st"] == "rejected"
        assert session.updates[-1]["note"] == "old teaching"
        assert client.post(f"/v1/library/red-list/claims/{UUID(int=3)}", headers=HEADERS,
                           json={"decision": "maybe"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_the_export_is_a_csv_with_file_pages_problem_and_evidence() -> None:
    try:
        response = _client(_Session()).get("/v1/library/red-list/export.csv", headers=HEADERS)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    lines = response.text.splitlines()
    assert lines[0].startswith("type,file,title,pages,problem")
    assert any(line.startswith("notes,imm-deck.pdf,IMM deck,14-15,unsupported_claims")
               for line in lines)


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
