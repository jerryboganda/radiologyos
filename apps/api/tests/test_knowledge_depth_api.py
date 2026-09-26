"""Knowledge depth and re-process over HTTP: auth, tenant/owner denial, contracts.

Dependency overrides and patched services only (no database); the tenant/RLS
proofs for the new tables live in evals/checks/test_knowledge_depth_live.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import knowledge_depth as depth_api
from apps.api.app.api import library as library_api
from apps.api.app.knowledge import merge_review, merges, notes, trust
from apps.api.app.library import tables as table_store
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.worker.app.datarights import registry
from fastapi.testclient import TestClient

OWNER = Principal(user_id=uuid4(), tenant_id=uuid4())
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
             / "20260926_0103_knowledge_depth.py")
NOW = datetime(2026, 9, 26, tzinfo=UTC)


class Session:
    async def commit(self) -> None:
        return None


@pytest.fixture()
def client() -> Iterator[TestClient]:
    for module in (depth_api, library_api):
        app.dependency_overrides[module.principal_context] = lambda: OWNER
        app.dependency_overrides[module.tenant_db_session] = lambda: Session()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_routes_are_mounted_and_require_identity() -> None:
    paths = app.openapi()["paths"]
    cid, mid = uuid4(), uuid4()
    for path in ("/v1/knowledge/concepts/{concept_id}/note",
                 "/v1/knowledge/concepts/{concept_id}/note/synthesize",
                 "/v1/knowledge/concepts/{concept_id}/note/verify",
                 "/v1/knowledge/concepts/{concept_id}/graph",
                 "/v1/knowledge/concepts/{concept_id}/figures",
                 "/v1/knowledge/conflicts/{conflict_id}/trust",
                 "/v1/knowledge/merges", "/v1/knowledge/merges/{merge_id}/decide",
                 "/v1/knowledge/merges/{merge_id}/undo",
                 "/v1/library/sources/{source_id}/reprocess"):
        assert path in paths, path
    anonymous = TestClient(app)
    assert anonymous.get(f"/v1/knowledge/concepts/{cid}/note").status_code == 401
    assert anonymous.post(f"/v1/knowledge/conflicts/{cid}/trust",
                          json={"trust": "a"}).status_code == 401
    assert anonymous.post(f"/v1/knowledge/merges/{mid}/undo").status_code == 401
    assert anonymous.post(f"/v1/library/sources/{cid}/reprocess").status_code == 401


def test_invisible_concepts_are_404_for_every_concept_route(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def nothing(*_args: Any) -> None:
        return None

    monkeypatch.setattr(notes, "note_state", nothing)
    monkeypatch.setattr(notes, "visible_concept", nothing)
    monkeypatch.setattr(notes, "verify_note", nothing)
    cid = uuid4()
    assert client.get(f"/v1/knowledge/concepts/{cid}/note").status_code == 404
    assert client.post(f"/v1/knowledge/concepts/{cid}/note/synthesize").status_code == 404
    assert client.post(f"/v1/knowledge/concepts/{cid}/note/verify",
                       json={"note_id": str(uuid4())}).status_code == 404
    assert client.get(f"/v1/knowledge/concepts/{cid}/graph").status_code == 404
    assert client.get(f"/v1/knowledge/concepts/{cid}/figures").status_code == 404
    assert client.get(f"/v1/knowledge/concepts/{cid}/graph?depth=3").status_code == 422


def test_synthesize_queues_the_callers_own_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, sent, audited = uuid4(), [], []

    async def visible(_s: Any, user: UUID, _c: UUID) -> UUID:
        assert user == OWNER.user_id
        return live

    async def fake_audit(_s: Any, _p: Any, action: str, *_rest: Any) -> None:
        audited.append(action)

    monkeypatch.setattr(notes, "visible_concept", visible)
    monkeypatch.setattr(depth_api, "audit", fake_audit)
    monkeypatch.setattr(depth_api, "enqueue_note", lambda *args: sent.append(args))
    response = client.post(f"/v1/knowledge/concepts/{uuid4()}/note/synthesize")
    assert response.status_code == 202 and response.json()["concept_id"] == str(live)
    assert sent == [(OWNER.tenant_id, OWNER.user_id, live)]
    assert audited == ["knowledge.note_requested"]


def test_verify_refuses_a_stale_or_conflicted_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*_args: Any) -> None:
        raise notes.NoteNotVerifiable("only a current draft can be verified")

    monkeypatch.setattr(notes, "verify_note", refuse)
    response = client.post(f"/v1/knowledge/concepts/{uuid4()}/note/verify",
                           json={"note_id": str(uuid4())})
    assert response.status_code == 409


def _conflict(trust_value: str | None = None) -> dict[str, Any]:
    side = {"statement": "s", "span": "span", "citation": {}}
    row = {"id": uuid4(), "concept_id": uuid4(), "concept_name": "X", "kind": "numeric",
           "description": "d", "status": "resolved", "resolution": "Trusted source A",
           "preferred_claim": None, "resolved_at": NOW, "created_at": NOW,
           "ai_label": "conflict", "ai_confidence": 0.9, "ai_rationale": "[A] vs [B]",
           "ai_context": "", "ai_cites": ["A"], "trust": trust_value}
    for key in ("a", "b"):
        row |= {f"{key}_id": uuid4(), **{f"{key}_{k}": v for k, v in side.items()}}
    return row


def test_trust_validates_the_choice_and_returns_the_verdict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_trust(_s: Any, principal: Principal, _c: UUID, choice: str,
                         _n: str) -> dict[str, Any] | None:
        calls.append(choice)
        if choice == "b":
            raise ValueError("conflict is already resolved")
        return _conflict(choice) if principal is OWNER else None

    monkeypatch.setattr(trust, "trust_conflict", fake_trust)
    url = f"/v1/knowledge/conflicts/{uuid4()}/trust"
    body = client.post(url, json={"trust": "a", "note": "Newer edition"}).json()
    assert body["trust"] == "a" and body["ai_label"] == "conflict"
    assert body["ai_cites"] == ["A"]
    assert client.post(url, json={"trust": "b"}).status_code == 409
    assert client.post(url, json={"trust": "c"}).status_code == 422
    assert client.post(url, json={"trust": "a", "extra": 1}).status_code == 422
    assert calls == ["a", "b"]


def _merge(status: str) -> dict[str, Any]:
    return {"id": uuid4(), "concept_a": uuid4(), "a_name": "A", "concept_b": uuid4(),
            "b_name": "B", "similarity": 0.85, "decision": "merge", "confidence": 0.6,
            "rationale": "r", "status": status, "survivor": None, "merged": None,
            "moved_claims": 0, "agent_version": "concept_resolver/v1", "created_at": NOW,
            "applied_at": None, "undone_at": None}


def test_merge_review_decide_and_undo_map_conflicts_to_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def listing(_s: Any, user: UUID, status: str | None) -> list[dict[str, Any]]:
        assert user == OWNER.user_id and status == "review"
        return [_merge("review")]

    async def decide(_s: Any, _p: Any, _m: UUID, decision: str) -> dict[str, Any] | None:
        if decision == "distinct":
            return None
        return _merge("applied")

    async def undo(*_args: Any) -> None:
        raise merges.MergeConflict("undo the later merge of the surviving concept first")

    monkeypatch.setattr(merge_review, "list_merges", listing)
    monkeypatch.setattr(merge_review, "decide", decide)
    monkeypatch.setattr(merge_review, "undo", undo)
    assert client.get("/v1/knowledge/merges").json()[0]["status"] == "review"
    mid = uuid4()
    assert client.post(f"/v1/knowledge/merges/{mid}/decide",
                       json={"decision": "merge"}).json()["status"] == "applied"
    assert client.post(f"/v1/knowledge/merges/{mid}/decide",
                       json={"decision": "distinct"}).status_code == 404
    assert client.post(f"/v1/knowledge/merges/{mid}/decide",
                       json={"decision": "maybe"}).status_code == 422
    assert client.post(f"/v1/knowledge/merges/{mid}/undo").status_code == 409


def test_reprocess_is_owner_only_refuses_a_running_job_and_queues_the_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job, queued, mine = uuid4(), [], uuid4()

    async def request(_s: Any, principal: Principal, source: UUID) -> dict[str, Any] | None:
        if source == mine:
            return {"source_id": source, "job_id": job, "retried_pages": 2}
        if source == job:
            raise table_store.ReprocessBusy("this source is being processed right now")
        return None

    monkeypatch.setattr(table_store, "request_reprocess", request)
    monkeypatch.setattr(library_api, "enqueue_ingest", lambda t, j: queued.append((t, j)))
    ok = client.post(f"/v1/library/sources/{mine}/reprocess")
    assert ok.status_code == 202 and ok.json()["retried_pages"] == 2
    assert queued == [(OWNER.tenant_id, job)]
    assert client.post(f"/v1/library/sources/{uuid4()}/reprocess").status_code == 404
    assert client.post(f"/v1/library/sources/{job}/reprocess").status_code == 409
    assert len(queued) == 1


def test_migration_is_expand_only_with_forced_rls_and_registered_tables() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", 1)[0]
    assert 'revision = "20260926_0103"' in source
    assert 'TABLES = ("concept_notes", "concept_merges", "source_tables")' in source
    for statement in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                      "tenant_id = app.current_tenant_id()", "REVOKE ALL ON {table} FROM PUBLIC",
                      "ON DELETE SET NULL (merged_into)", "'knowledge_depth'"):
        assert statement in upgrade
    for forbidden in ("DROP TABLE", "DROP COLUMN", "RENAME", "SECURITY DEFINER"):
        assert forbidden not in upgrade
    # The only DROP is the in-place widening of the job step vocabulary.
    assert upgrade.count("DROP ") == 1
    assert "DROP CONSTRAINT IF EXISTS job_steps_step_check" in upgrade
    owned = {item.table: item for item in registry.OWNED}
    assert owned["concept_notes"].erased_by == owned["concept_merges"].erased_by == "direct"
    assert owned["source_tables"].erased_by == "source_cascade"
    assert "merged_into" in owned["concepts"].where
