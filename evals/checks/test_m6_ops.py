"""M6 eval gate: delete purge, export, parked billing, and object isolation.

Covers slices T, U, and the object/cache isolation part of V:
  T  billing stays parked (ADR 0011): absent unless switched on
  U  source delete and account erasure purge data, derived artifacts, caches,
     and objects; the export's notes and vault leave deleted sources out
  V  data-rights endpoints are durable, authenticated jobs

ADR 0031 retired the in-memory preview this gate used to exercise. These
checks drive the durable code (``apps/api/app/library/service.py``,
``apps/worker/app/datarights/*``, ``packages/library/storage.py``) with a
statement-recording session; the row-level proofs against PostgreSQL as the
runtime role are ``test_library_live.py`` and ``test_data_rights_live.py``.
The preview-only capability matrix and release-audit endpoints went with the
preview; release evidence is the same-SHA record from ``scripts/evidence_record.py``.

All content is synthetic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.library import service
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.worker.app.datarights import delete, jobs, notes, registry, vault_sql
from apps.worker.app.datarights.vault import render_vault
from evals.checks._m6_support import RecordingSession, Result, TenantTx
from evals.checks._vault_support import CHEST, rows_for_user_a, without_source
from fastapi.testclient import TestClient
from packages.library import storage
from packages.library.storage import MemoryObjectStore

client = TestClient(app)
TENANT_A = UUID("30000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("30000000-0000-4000-8000-00000000000b")
USER_A = UUID("10000000-0000-4000-8000-00000000000a")
HEADERS = {"x-user-id": str(USER_A), "x-tenant-id": str(TENANT_A), "x-role": "org_admin"}
SOURCE = UUID("50000000-0000-4000-8000-000000000001")


def _store_with_two_tenants() -> MemoryObjectStore:
    store = MemoryObjectStore()
    for tenant in (TENANT_A, TENANT_B):
        store.put(storage.original_key(tenant, SOURCE, "pdf"), b"%PDF", "application/pdf")
        store.put(storage.page_image_key(tenant, SOURCE, 1), b"png", "image/png")
        store.put(storage.figure_image_key(tenant, SOURCE, 1, 1), b"png", "image/png")
    return store


# ---------------------------------------------------------------- slice U


async def test_purge_removes_the_source_its_jobs_and_orphaned_derivatives() -> None:
    session = RecordingSession([
        ("SELECT concept_id FROM claims", lambda _: Result([(uuid4(),)])),
        ("SELECT content_sha256 FROM chunks", lambda _: Result([("a" * 64,)])),
    ])
    await service.purge_source_rows(session, SOURCE)  # type: ignore[arg-type]
    sql = session.sql()
    assert any(s.startswith("DELETE FROM jobs WHERE entity_id") for s in sql)
    # Pages, blocks, figures, chunks, claims, mappings, and cards cascade from it.
    assert any(s.startswith("DELETE FROM sources WHERE id") for s in sql)
    cache = next(s for s in sql if s.startswith("DELETE FROM embedding_cache"))
    concepts = next(s for s in sql if s.startswith("DELETE FROM concepts"))
    assert "NOT EXISTS" in cache and "NOT EXISTS" in concepts  # shared rows survive
    assert all(p.get("id") == SOURCE for _, p, _ in session.calls if "id" in p)


async def test_purge_skips_cache_and_concept_sweeps_when_nothing_was_derived() -> None:
    session = RecordingSession()
    await service.purge_source_rows(session, SOURCE)  # type: ignore[arg-type]
    # The affected-concept lookup still runs; no cache or concept sweep (DELETE) does.
    assert not [s for s in session.sql()
                if "DELETE FROM embedding_cache" in s or "DELETE FROM concepts" in s]


async def test_delete_removes_objects_first_then_rows_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = RecordingSession([("SELECT legal_hold", lambda _: Result([False]))])
    store = _store_with_two_tenants()

    async def owned(*_: Any) -> dict[str, Any]:
        return {"id": SOURCE}

    monkeypatch.setattr(service, "get_source", owned)
    principal = Principal(USER_A, TENANT_A)
    assert await service.delete_source(session, store, principal, SOURCE)  # type: ignore[arg-type]
    assert not [k for k in store.objects if k.startswith(f"tenants/{TENANT_A}/")]
    assert len([k for k in store.objects if k.startswith(f"tenants/{TENANT_B}/")]) == 3
    assert any("INSERT INTO audit_log" in s for s in session.sql())
    assert session.commits == 1


async def test_delete_refuses_a_source_the_caller_does_not_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, store = RecordingSession(), _store_with_two_tenants()

    async def not_mine(*_: Any) -> None:
        return None

    monkeypatch.setattr(service, "get_source", not_mine)
    principal = Principal(USER_A, TENANT_A)
    assert not await service.delete_source(session, store, principal, SOURCE)  # type: ignore[arg-type]
    assert session.calls == [] and len(store.objects) == 6


async def test_legal_hold_blocks_delete_and_touches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = RecordingSession([("SELECT legal_hold", lambda _: Result([True]))])
    store = _store_with_two_tenants()

    async def owned(*_: Any) -> dict[str, Any]:
        return {"id": SOURCE}

    monkeypatch.setattr(service, "get_source", owned)
    with pytest.raises(service.SourceOnHold):
        await service.delete_source(session, store, Principal(USER_A, TENANT_A),  # type: ignore[arg-type]
                                    SOURCE)
    assert len(store.objects) == 6 and session.commits == 0


def _erasure_script(held: UUID, free: UUID) -> list[tuple[str, Any]]:
    return [
        ("SELECT id, legal_hold FROM sources", lambda _: Result([(free, False), (held, True)])),
        ("SELECT id FROM data_jobs", lambda _: Result([(uuid4(),)])),
        ("erase_user_identity", lambda _: Result(["stubbed"])),
        ("DELETE FROM", lambda _: Result(rowcount=1)),
    ]


async def test_account_erasure_runs_every_step_in_the_tenant_and_keeps_held_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held, free, job_id = uuid4(), uuid4(), uuid4()
    session = RecordingSession(_erasure_script(held, free))
    tx, steps, purged = TenantTx(session), [], []
    finished: dict[str, Any] = {}

    async def load(_s: Any, _job: UUID, kind: str) -> dict[str, Any]:
        return {"user_id": USER_A, "status": "running" if finished else "queued"}

    async def record_step(_s: Any, _job: UUID, step: str, *_: Any) -> None:
        steps.append(step)

    async def finish(_s: Any, _job: UUID, detail: dict[str, Any], *_: Any) -> bool:
        finished.update(detail)
        return True

    async def purge(_s: Any, source_id: UUID) -> None:
        purged.append(source_id)

    async def nothing(*_: Any) -> None:
        return None

    for name, fake in (("load", load), ("set_step", record_step), ("finish", finish),
                       ("start", nothing)):
        monkeypatch.setattr(jobs, name, fake)
    monkeypatch.setattr(delete, "tenant_tx", tx)
    monkeypatch.setattr(delete, "purge_source_rows", purge)
    store = MemoryObjectStore()
    store.put(storage.original_key(TENANT_A, free, "pdf"), b"x", "application/pdf")
    store.put(storage.original_key(TENANT_A, held, "pdf"), b"x", "application/pdf")
    store.put(storage.original_key(TENANT_B, free, "pdf"), b"x", "application/pdf")
    deps: Any = type("Deps", (), {"engine": None, "store": store})()

    assert await delete.run_delete(deps, TENANT_A, job_id) == "succeeded"
    assert steps == ["study_rows", "sources", "sources", "exports", "idp_sessions", "identity"]
    assert purged == [free] and finished["held_sources"] == 1
    assert set(tx.tenants) == {TENANT_A}
    assert storage.original_key(TENANT_A, held, "pdf") in store.objects
    assert storage.original_key(TENANT_B, free, "pdf") in store.objects
    assert storage.original_key(TENANT_A, free, "pdf") not in store.objects
    direct = [s for s in session.sql() if s.startswith("DELETE FROM") and " t WHERE " in s]
    assert len(direct) == len(registry.DIRECT_DELETE_ORDER)
    assert all(p == {"u": USER_A} for s, p, _ in session.calls if " t WHERE " in s)


def test_a_deleted_source_leaves_the_export_vault_and_notes() -> None:
    assert "deleted_at IS NULL" in vault_sql.LIVE_SOURCES
    for statement in (vault_sql.CLAIMS_SQL, vault_sql.CONCEPTS_SQL, vault_sql.EDGES_SQL):
        assert vault_sql.LIVE_SOURCES in str(statement)
    files = render_vault(without_source(rows_for_user_a(), CHEST))
    assert CHEST.hex[:8] not in "\n".join(files.values())


async def test_exported_notes_cite_every_card_and_claim() -> None:
    card = {"curriculum_code": "CHEST", "topic": "Pleura", "front": "Q?", "back": "A.",
            "title": "Synthetic chest notes", "page_from": "2", "page_to": "2"}
    claim = {"name": "Pleural effusion", "statement": "S.", "evidence_span": "E.",
             "status": "disputed", "page_from": 2, "page_to": 3, "title": None}
    cards = await notes.cards_markdown(
        RecordingSession([("FROM cards", lambda _: Result([card]))]), USER_A)  # type: ignore[arg-type]
    claims = await notes.claims_markdown(
        RecordingSession([("FROM claims", lambda _: Result([claim]))]), USER_A)  # type: ignore[arg-type]
    assert "_Source: Synthetic chest notes, p. 2_" in cards
    assert "- S. (disputed)" in claims and "Source: deleted source, pp. 2-3" in claims


# ---------------------------------------------------------------- slice T


def test_billing_is_parked_and_absent_unless_switched_on() -> None:
    for path in ("/v1/billing/plans", "/v1/billing/subscription"):
        assert client.get(path, headers=HEADERS).status_code == 404


# ---------------------------------------------------------------- slice V


def test_release_data_rights_are_durable_jobs_not_placeholders() -> None:
    """Export/delete are real queued jobs (ADR 0018), no longer 501 boundaries."""
    paths = app.openapi()["paths"]
    for path, method in (("/v1/me/export", "post"), ("/v1/me", "delete"),
                         ("/v1/me/exports", "get"), ("/v1/me/exports/{job_id}/download", "get")):
        assert method in paths[path], (path, method)
        assert "501" not in paths[path][method]["responses"]


def test_release_data_rights_require_authentication() -> None:
    for method, path in (("post", "/v1/me/export"), ("delete", "/v1/me")):
        assert getattr(client, method)(path).status_code in {401, 403}


# --------------------------------------------------- object/cache isolation


def test_every_object_key_is_tenant_prefixed_and_never_collides() -> None:
    job, user, image = uuid4(), uuid4(), uuid4()
    for tenant, other in ((TENANT_A, TENANT_B), (TENANT_B, TENANT_A)):
        keys = [storage.original_key(tenant, SOURCE, "pdf"),
                storage.page_image_key(tenant, SOURCE, 1),
                storage.figure_image_key(tenant, SOURCE, 1, 1),
                storage.export_key(tenant, job),
                storage.tutor_image_key(tenant, user, image, "png")]
        for key in keys:
            assert key.startswith(f"tenants/{tenant}/")
            storage.require_tenant_key(tenant, key)
            with pytest.raises(PermissionError):
                storage.require_tenant_key(other, key)
    assert storage.export_key(TENANT_A, job) != storage.export_key(TENANT_B, job)


def test_a_prefix_delete_never_reaches_another_tenant() -> None:
    store = _store_with_two_tenants()
    store.delete_prefix(storage.source_prefix(TENANT_A, SOURCE) + "/")
    assert all(key.startswith(f"tenants/{TENANT_B}/") for key in store.objects)
    assert len(store.objects) == 3
