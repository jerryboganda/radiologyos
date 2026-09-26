"""Data rights (ADR 0018): registry coverage, endpoint contracts, export helpers.

The database-backed export/delete proofs run as the runtime role in
evals/checks/test_data_rights_live.py; these tests need no services.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import data_rights, knowledge
from apps.api.app.datarights import service
from apps.api.app.main import app
from apps.worker.app.datarights import export, registry
from fastapi.testclient import TestClient
from packages.library.storage import MemoryObjectStore, export_key

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
TENANT = UUID("20000000-0000-0000-0000-000000000002")
USER = UUID("10000000-0000-0000-0000-000000000001")
HEADERS = {"x-user-id": str(USER), "x-tenant-id": str(TENANT)}
client = TestClient(app)


def _tables() -> set[str]:
    found: set[str] = set()
    for path in MIGRATIONS.glob("*.py"):
        found |= set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", path.read_text("utf-8")))
    return found


def test_every_table_is_exported_and_erased_or_explicitly_exempt() -> None:
    listed = {item.table for item in registry.OWNED}
    assert len(listed) == len(registry.OWNED), "duplicate registry entry"
    assert listed.isdisjoint(registry.EXEMPT)
    missing = _tables() - listed - set(registry.EXEMPT)
    assert not missing, f"add these tables to the data-rights registry: {sorted(missing)}"
    direct = {item.table for item in registry.OWNED if item.erased_by == "direct"}
    assert direct == set(registry.DIRECT_DELETE_ORDER)
    order = registry.DIRECT_DELETE_ORDER
    assert order.index("card_reviews") < order.index("cards")
    assert order.index("attempts") < order.index("exams") < order.index("questions")
    assert order.index("tutor_messages") < order.index("tutor_threads")


def test_registry_sql_is_parameterised_by_user_only() -> None:
    for item in registry.OWNED:
        assert ":u" in item.where and ";" not in item.where, item.table
        assert registry.select_sql(item).startswith("SELECT row_to_json(t)")
    with pytest.raises(ValueError):
        registry.delete_sql("users")


def test_migration_is_expand_only_with_forced_rls_and_narrow_definers() -> None:
    source = (MIGRATIONS / "20260926_0012_data_rights.py").read_text("utf-8")
    assert 'revision = "20260926_0012"' in source
    assert 'down_revision = "20260926_0011"' in source
    upgrade = source.split("def downgrade")[0]
    assert "DROP " not in upgrade and "RENAME" not in upgrade
    assert "ALTER TABLE data_jobs FORCE ROW LEVEL SECURITY" in source
    for fn in ("app.expired_data_exports(timestamptz)", "app.erase_user_identity(uuid)"):
        assert f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC" in source
    assert "j.status = 'running'" in source  # eraser refuses without a running delete job


def test_data_rights_require_authentication() -> None:
    assert client.post("/v1/me/export").status_code == 401
    assert client.get("/v1/me/exports").status_code == 401
    assert client.get(f"/v1/me/exports/{uuid4()}/download").status_code == 401
    assert client.request("DELETE", "/v1/me", json={"confirmation": "x"}).status_code == 401


def _row(kind: str, status: str = "queued") -> dict[str, Any]:
    return {"id": uuid4(), "kind": kind, "status": status, "step": "queued", "byte_size": None,
            "detail": {}, "error_code": None, "created_at": datetime.now(UTC),
            "finished_at": None, "expires_at": None}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, UUID]]]:
    sent: list[tuple[str, UUID]] = []
    app.dependency_overrides[data_rights.tenant_db_session] = lambda: object()
    app.dependency_overrides[knowledge.tenant_db_session] = lambda: object()
    monkeypatch.setattr(data_rights, "enqueue", lambda kind, t, j: sent.append((kind, j)))
    yield sent
    app.dependency_overrides.clear()


def test_delete_requires_the_typed_confirmation(
    wired: list[tuple[str, UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("delete")

    async def request_job(session: Any, principal: Any, kind: str) -> Any:
        assert principal.user_id == USER and kind == "delete"
        return row, True

    monkeypatch.setattr(service, "request_job", request_job)
    wrong = client.request("DELETE", "/v1/me", headers=HEADERS, json={"confirmation": "yes"})
    assert wrong.status_code == 422 and wired == []
    assert client.request("DELETE", "/v1/me", headers=HEADERS).status_code == 422
    ok = client.request("DELETE", "/v1/me", headers=HEADERS,
                        json={"confirmation": "  Delete my account "})
    assert ok.status_code == 202 and ok.json()["kind"] == "delete"
    assert wired == [("delete", row["id"])]


def test_export_is_queued_and_refused_while_deleting(
    wired: list[tuple[str, UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("export")

    async def request_job(session: Any, principal: Any, kind: str) -> Any:
        return row, False

    monkeypatch.setattr(service, "request_job", request_job)
    response = client.post("/v1/me/export", headers=HEADERS)
    assert response.status_code == 202 and response.json()["download_path"] is None
    assert wired == [("export", row["id"])]

    async def deleting(session: Any, principal: Any, kind: str) -> Any:
        raise service.AccountDeleting("account deletion is in progress")

    monkeypatch.setattr(service, "request_job", deleting)
    assert client.post("/v1/me/export", headers=HEADERS).status_code == 409


def test_download_streams_only_the_callers_tenant_object(
    wired: list[tuple[str, UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryObjectStore()
    job = uuid4()
    store.put(export_key(TENANT, job), b"PK-zip-bytes", "application/zip")
    monkeypatch.setattr(data_rights, "get_store", lambda: store)
    found = {"id": job, "object_key": export_key(TENANT, job), "byte_size": 12,
             "finished_at": datetime(2026, 9, 26, tzinfo=UTC)}

    async def for_download(session: Any, principal: Any, job_id: UUID) -> Any:
        return found if job_id == job else None

    monkeypatch.setattr(service, "export_for_download", for_download)
    response = client.get(f"/v1/me/exports/{job}/download", headers=HEADERS)
    assert response.status_code == 200 and response.content == b"PK-zip-bytes"
    assert response.headers["cache-control"] == "no-store"
    assert "radbrain-export-20260926.zip" in response.headers["content-disposition"]
    assert client.get(f"/v1/me/exports/{uuid4()}/download", headers=HEADERS).status_code == 404
    found["object_key"] = export_key(uuid4(), job)  # another tenant's key: never served
    assert client.get(f"/v1/me/exports/{job}/download", headers=HEADERS).status_code == 404


def test_mapping_recode_requires_a_code(wired: list[tuple[str, UUID]]) -> None:
    response = client.post(f"/v1/knowledge/mappings/{uuid4()}/decide", headers=HEADERS,
                           json={"decision": "code"})
    assert response.status_code == 422
    bad = client.post(f"/v1/knowledge/mappings/{uuid4()}/decide", headers=HEADERS,
                      json={"decision": "maybe"})
    assert bad.status_code == 422
    systems = client.get("/v1/knowledge/curriculum/systems", headers=HEADERS).json()
    assert systems and all(s["code"] and s["title"] for s in systems)


def test_export_copies_objects_counts_missing_and_refuses_foreign_keys() -> None:
    store = MemoryObjectStore()
    key = f"tenants/{TENANT}/sources/{uuid4()}/original.pdf"
    store.put(key, b"%PDF-synthetic", "application/pdf")
    gone = f"tenants/{TENANT}/sources/{uuid4()}/original.pdf"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        copied, missing = export._copy_objects(
            store, zf, TENANT, [("files/a/original.pdf", key), ("files/b/original.pdf", gone)])
        with pytest.raises(PermissionError):
            export._copy_objects(store, zf, TENANT, [("x", f"tenants/{uuid4()}/x")])
    assert (copied, missing) == (1, 1)
    with zipfile.ZipFile(buffer) as zf:
        assert zf.read("files/a/original.pdf") == b"%PDF-synthetic"


def test_export_file_names_are_sanitised() -> None:
    assert export.safe_name("../../etc/passwd", "x") == "passwd"
    assert export.safe_name("C:\\notes\\chest <1>.pdf", "x") == "chest _1_.pdf"
    assert export.safe_name(None, "original") == "original"
    assert export.safe_name("...", "original") == "original"
