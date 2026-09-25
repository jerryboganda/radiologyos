"""M6 eval gate: export/delete purge, isolation boundaries, and ops honesty.

Covers slices T, U, and the object/cache isolation part of V that can be
verified without a billing provider:
  T  billing degradation and the caps that apply while billing is gated
  U  export and delete across data, derived artifacts, caches and queues
  V  the release-boundary behaviour that must not be faked

Stripe webhooks, caps enforcement against a real provider, and the
load/backup/restore evidence in slice V need a provider decision and the
protected staging environment; they are recorded as open, not simulated.

All content is synthetic.
"""

from __future__ import annotations

from uuid import UUID

from apps.api.app.main import app, settings
from apps.api.app.preview.knowledge import extract_source
from apps.api.app.preview.library import derive_object_key, ingest_source
from apps.api.app.preview.operations import (
    billing_status,
    capabilities,
    markdown_export,
    release_audit,
)
from apps.api.app.preview.service import reset_preview_state
from evals.checks._harness import (
    CHEST,
    HEAD,
    OWNER_A,
    OWNER_B,
    TENANT_A,
    TENANT_B,
    new_state,
    seed,
)
from fastapi.testclient import TestClient

client = TestClient(app)
BASE = {
    "x-user-id": "10000000-0000-0000-0000-00000000000a",
    "x-tenant-id": "30000000-0000-0000-0000-00000000000a",
}


def setup_function() -> None:
    reset_preview_state()
    settings.preview_enabled = True


def teardown_function() -> None:
    settings.preview_enabled = False
    reset_preview_state()


def seeded_with_claims():
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m6-source")
    extract_source(state, TENANT_A, OWNER_A, source.id)
    return state, source


# ---------------------------------------------------------------- slice U


def test_delete_purges_every_derived_artifact() -> None:
    """Slice U: delete must not leave derived data behind."""
    state, source = seeded_with_claims()
    assert state.source_chunks(TENANT_A, source.id)
    assert state.claims(TENANT_A)
    assert state.jobs(TENANT_A)

    assert state.soft_delete_source(TENANT_A, source.id, state.now()) is True

    assert state.source_chunks(TENANT_A, source.id) == []
    assert state.source_figures(TENANT_A, source.id) == []
    assert state.page(TENANT_A, source.id, 1) is None
    assert state.page_blocks(TENANT_A, source.id, 1) == []
    assert state.claims(TENANT_A) == []
    assert state.jobs(TENANT_A) == []
    # The source row is retained as a tombstone for the audit trail.
    tombstone = state.source(TENANT_A, source.id)
    assert tombstone is not None
    assert tombstone.status == "deleted"
    assert tombstone.deleted_at is not None


def test_delete_releases_the_idempotency_key_for_reingestion() -> None:
    state, source = seeded_with_claims()
    state.soft_delete_source(TENANT_A, source.id, state.now())
    assert state.idempotent_source(TENANT_A, "m6-source") is None

    again, _job = ingest_source(
        state, TENANT_A, OWNER_A, "Synthetic again", "note", CHEST, "m6-source"
    )
    assert again.id != source.id
    assert again.status == "ready"
    assert again.deleted_at is None


def test_delete_is_idempotent_and_refuses_a_second_purge() -> None:
    state, source = seeded_with_claims()
    assert state.soft_delete_source(TENANT_A, source.id, state.now()) is True
    assert state.soft_delete_source(TENANT_A, source.id, state.now()) is False


def test_delete_does_not_touch_another_tenants_data() -> None:
    state = new_state()
    a_source, _ = ingest_source(state, TENANT_A, OWNER_A, "A", "note", CHEST, "m6-a")
    b_source, _ = ingest_source(state, TENANT_B, OWNER_B, "B", "note", HEAD, "m6-b")
    extract_source(state, TENANT_B, OWNER_B, b_source.id)

    assert state.soft_delete_source(TENANT_A, a_source.id, state.now()) is True

    assert state.source_chunks(TENANT_B, b_source.id)
    assert state.claims(TENANT_B)
    assert state.source(TENANT_B, b_source.id).status == "ready"


def test_delete_through_the_api_is_owner_scoped_and_audited() -> None:
    created = client.post(
        "/v1/preview/sources",
        headers={**BASE, "Idempotency-Key": "m6-api"},
        json={"title": "Synthetic", "kind": "note", "content": CHEST},
    )
    source_id = created.json()[0]["id"]

    other_owner = client.delete(
        f"/v1/preview/sources/{source_id}",
        headers={**BASE, "x-user-id": "10000000-0000-0000-0000-0000000000ff"},
    )
    assert other_owner.status_code == 404

    other_tenant = client.delete(
        f"/v1/preview/sources/{source_id}",
        headers={
            "x-user-id": "10000000-0000-0000-0000-00000000000b",
            "x-tenant-id": "30000000-0000-0000-0000-00000000000b",
        },
    )
    assert other_tenant.status_code == 404

    deleted = client.delete(f"/v1/preview/sources/{source_id}", headers=BASE)
    assert deleted.status_code == 202
    assert deleted.json()["status"] == "deleted"
    assert client.get("/v1/preview/sources", headers=BASE).json() == []


def test_a_deleted_source_disappears_from_search_and_export() -> None:
    created = client.post(
        "/v1/preview/sources",
        headers={**BASE, "Idempotency-Key": "m6-search"},
        json={"title": "Synthetic", "kind": "note", "content": CHEST},
    )
    source_id = created.json()[0]["id"]
    assert client.post("/v1/preview/search", headers=BASE, json={"query": "costophrenic"}).json()[
        "chunks"
    ]

    client.delete(f"/v1/preview/sources/{source_id}", headers=BASE)

    assert (
        client.post("/v1/preview/search", headers=BASE, json={"query": "costophrenic"}).json()[
            "chunks"
        ]
        == []
    )
    assert (
        source_id not in client.get("/v1/preview/export/markdown", headers=BASE).json()["markdown"]
    )


# ---------------------------------------------------- export and round trip


def test_markdown_export_cites_every_derived_sentence() -> None:
    state, source = seeded_with_claims()
    document = markdown_export(state, TENANT_A, OWNER_A)

    assert document.startswith("# radbrain preview export")
    assert "Not a Core Library artifact" in document
    # One Source line per visible source and one Citation line per chunk: every
    # piece of exported body content is attributable.
    assert document.count("Source: `") == 1
    assert document.count("Citation: `") == len(state.source_chunks(TENANT_A, source.id))
    assert document.count("Citation: `") > 0


def test_markdown_export_links_back_to_real_pages() -> None:
    state, source = seeded_with_claims()
    document = markdown_export(state, TENANT_A, OWNER_A)

    for chunk in state.source_chunks(TENANT_A, source.id):
        assert f"p. {chunk.page_no}" in document
        assert f"block `{chunk.block_start}`" in document


def test_markdown_export_is_tenant_scoped() -> None:
    state, _ = seeded_with_claims()
    ingest_source(state, TENANT_B, OWNER_B, "Head", "note", HEAD, "m6-b")

    a_doc = markdown_export(state, TENANT_A, OWNER_A)
    b_doc = markdown_export(state, TENANT_B, OWNER_B)

    a_source = state.sources(TENANT_A)[0]
    b_source = state.sources(TENANT_B)[0]
    assert str(a_source.id) in a_doc
    assert str(b_source.id) not in a_doc
    assert str(b_source.id) in b_doc
    assert "costophrenic" in a_doc
    assert "costophrenic" not in b_doc


def test_markdown_export_is_owner_scoped_within_a_tenant() -> None:
    state, _ = seeded_with_claims()
    other, _job = ingest_source(state, TENANT_A, OWNER_B, "Owned by B", "note", HEAD, "m6-owner-b")

    document = markdown_export(state, TENANT_A, OWNER_A)
    assert str(other.id) not in document
    assert "Owned by B" not in document


def test_markdown_export_is_deterministic() -> None:
    state, _ = seeded_with_claims()
    assert markdown_export(state, TENANT_A, OWNER_A) == markdown_export(state, TENANT_A, OWNER_A)


# --------------------------------------------------------------- slice T


def test_billing_reports_preview_only_and_never_a_live_subscription() -> None:
    status = billing_status(new_state(), TENANT_A)
    assert status["provider"] == "mock_stripe_test_mode"
    assert status["status"] == "preview_only"
    message = str(status["message"])
    # No customer, checkout, portal or charge may be implied to exist.
    for absent in ("Stripe customer", "checkout", "portal", "charge"):
        assert absent in message
    assert "No " in message or "no " in message


def test_billing_never_reports_a_live_subscription_over_http() -> None:
    body = client.get("/v1/preview/billing/status", headers=BASE).json()
    assert body["mode"] == "preview"
    assert body["status"] == "preview_only"
    assert body["provider"] == "mock_stripe_test_mode"


def test_billing_is_tenant_scoped() -> None:
    state = new_state()
    state.tenant(TENANT_A).billing[TENANT_A] = {"plan": "synthetic-probe"}
    assert billing_status(state, TENANT_B).get("plan") != "synthetic-probe"


# --------------------------------------------------------------- slice V


def test_release_data_rights_refuse_explicitly() -> None:
    """Release boundaries return 501 rather than a fake job or a fake payload."""
    export = client.post("/v1/me/export", headers=BASE)
    assert export.status_code == 501
    assert "not available in preview mode" in export.json()["detail"]

    delete = client.delete("/v1/me", headers=BASE)
    assert delete.status_code == 501
    assert "not available in preview mode" in delete.json()["detail"]


def test_release_data_rights_require_authentication() -> None:
    """Unauthenticated callers must be rejected before the 501 boundary."""
    for method, path in (("post", "/v1/me/export"), ("delete", "/v1/me")):
        assert getattr(client, method)(path).status_code in {401, 403}


def test_capability_matrix_is_explicit_about_blocked_slices() -> None:
    matrix = {item["slice"]: item for item in capabilities()}

    assert set(matrix) == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    # A-D are the M0 staging gate and release is Z; both stay blocked.
    for letter in "ABCDZ":
        assert matrix[letter]["status"] == "blocked", letter
    for letter in "EFGHIJKLMNOPQRSTUVWXY":
        assert matrix[letter]["status"] == "preview", letter


def test_release_audit_reports_the_open_gates() -> None:
    audit = release_audit()
    assert audit["status"] == "blocked"
    blocked = " ".join(audit["blocked"])
    for expected in (
        "m0:staging-acceptance",
        "m1:staging-evidence",
        "m7:staging-evidence",
        "release:human-approvals",
    ):
        assert expected in blocked
    # Nothing may claim acceptance.
    assert "accepted" not in blocked


# --------------------------------------------------- object/cache isolation


def test_object_keys_for_two_tenants_never_collide() -> None:
    keys = {
        derive_object_key(tenant, UUID(int=7), "pages/1.png") for tenant in (TENANT_A, TENANT_B)
    }
    assert len(keys) == 2
    assert all(key.startswith("tenants/") for key in keys)


def test_seeding_two_tenants_keeps_all_state_separate() -> None:
    state = new_state()
    seed(state, TENANT_A, OWNER_A)
    seed(state, TENANT_B, OWNER_B)

    assert {s.tenant_id for s in state.sources(TENANT_A)} == {TENANT_A}
    assert {s.tenant_id for s in state.sources(TENANT_B)} == {TENANT_B}
    assert {c.tenant_id for c in state.claims(TENANT_A)} == {TENANT_A}
    assert {c.tenant_id for c in state.claims(TENANT_B)} == {TENANT_B}
    assert state.thread(TENANT_A, OWNER_A) == []
    assert state.thread(TENANT_B, OWNER_B) == []
