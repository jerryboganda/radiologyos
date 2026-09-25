"""M2 eval gate: extraction, entity resolution, conflicts, and editor authority.

Covers slices I, J, K, L of the A-Z queue:
  I  extraction workers, schemas, versioning, and the mock/local route boundary
  J  entity resolution and the tenant-isolated knowledge graph
  K  claims, explicit conflicts, curriculum seed/mapping, concept pages
  L  editor queues for mappings/conflicts with authorization and audit

All content is synthetic.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from apps.api.app.main import app, settings
from apps.api.app.preview.knowledge import (
    claims,
    concepts,
    conflicts,
    ensure_knowledge,
    extract_source,
)
from apps.api.app.preview.library import ingest_source
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


def editor_headers(role: str) -> dict[str, str]:
    return {**BASE, "x-role": role}


def setup_function() -> None:
    reset_preview_state()
    settings.preview_enabled = True


def teardown_function() -> None:
    settings.preview_enabled = False
    reset_preview_state()


# ---------------------------------------------------------------- slice I


def test_extraction_emits_one_cited_claim_per_chunk() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m2-extract")
    chunks = state.source_chunks(TENANT_A, source.id)

    produced = extract_source(state, TENANT_A, OWNER_A, source.id)

    assert len(produced) == len(chunks)
    for claim in produced:
        assert claim.tenant_id == TENANT_A
        assert claim.source_id == source.id
        assert claim.text.strip()
        citation = claim.citation
        assert citation is not None
        # Every claim must carry a resolvable citation or it is not usable.
        assert citation["source_id"] == str(source.id)
        assert int(citation["page_no"]) >= 1
        assert citation["block_id"]


def test_extraction_is_idempotent_and_never_duplicates_claims() -> None:
    state = new_state()
    source, _ = ingest_source(
        state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m2-extract-idem"
    )

    first = extract_source(state, TENANT_A, OWNER_A, source.id)
    second = extract_source(state, TENANT_A, OWNER_A, source.id)

    assert {c.id for c in first} == {c.id for c in second}
    assert len(state.claims(TENANT_A)) == len(first)


def test_extraction_refuses_a_source_owned_by_someone_else() -> None:
    state = new_state()
    source, _ = ingest_source(
        state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m2-extract-owner"
    )

    with pytest.raises(LookupError):
        extract_source(state, TENANT_A, OWNER_B, source.id)


def test_extraction_refuses_a_quarantined_source() -> None:
    state = new_state()
    source, _ = ingest_source(
        state,
        TENANT_A,
        OWNER_A,
        "Quarantined",
        "note",
        "MRN: 44556677 synthetic identifier",
        "m2-extract-quar",
    )
    assert source.status == "quarantined"

    with pytest.raises(LookupError):
        extract_source(state, TENANT_A, OWNER_A, source.id)


def test_extraction_refuses_across_tenants() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m2-extract-x")

    with pytest.raises(LookupError):
        extract_source(state, TENANT_B, OWNER_B, source.id)
    assert state.claims(TENANT_B) == []


# ---------------------------------------------------------------- slice J


def test_knowledge_fixture_is_created_once_and_is_idempotent() -> None:
    state = new_state()
    ensure_knowledge(state, TENANT_A, OWNER_A)
    before = len(state.claims(TENANT_A))
    ensure_knowledge(state, TENANT_A, OWNER_A)

    assert len(state.claims(TENANT_A)) == before
    assert concepts(state, TENANT_A, OWNER_A)
    assert conflicts(state, TENANT_A, OWNER_A)


def test_concepts_carry_tenant_id_and_backing_claims() -> None:
    state = new_state()
    seed(state)
    found = concepts(state, TENANT_A, OWNER_A)

    assert found
    claim_ids = {str(c.id) for c in state.claims(TENANT_A)}
    for concept in found:
        assert concept["tenant_id"] == str(TENANT_A)
        assert concept["name"]
        assert concept["type"]
        # A concept must be grounded in at least one real claim.
        assert concept["claim_ids"]
        assert set(concept["claim_ids"]) <= claim_ids


def test_duplicate_concepts_are_not_created_for_the_same_fixture() -> None:
    """Slice J: entity resolution must not fan out on repeated seeding."""
    state = new_state()
    seed(state)
    first = {c["name"] for c in concepts(state, TENANT_A, OWNER_A)}
    seed(state)
    ensure_knowledge(state, TENANT_A, OWNER_A)
    second = [c["name"] for c in concepts(state, TENANT_A, OWNER_A)]

    assert len(second) == len(set(second)), "concept names must be unique per tenant"
    assert first <= set(second)


def test_the_graph_is_tenant_isolated() -> None:
    state = new_state()
    seed(state, TENANT_A, OWNER_A)
    seed(state, TENANT_B, OWNER_B)

    a_ids = {c["id"] for c in concepts(state, TENANT_A, OWNER_A)}
    b_ids = {c["id"] for c in concepts(state, TENANT_B, OWNER_B)}
    assert a_ids and b_ids
    assert a_ids.isdisjoint(b_ids)

    for concept in concepts(state, TENANT_A, OWNER_A):
        assert concept["tenant_id"] == str(TENANT_A)
    for concept in concepts(state, TENANT_B, OWNER_B):
        assert concept["tenant_id"] == str(TENANT_B)


def test_claims_never_cross_tenants() -> None:
    state = new_state()
    seed(state, TENANT_A, OWNER_A)
    seed(state, TENANT_B, OWNER_B)

    a_claims = claims(state, TENANT_A, OWNER_A)
    b_claims = claims(state, TENANT_B, OWNER_B)
    assert {c.id for c in a_claims}.isdisjoint({c.id for c in b_claims})
    assert all(c.tenant_id == TENANT_A for c in a_claims)
    assert all(c.tenant_id == TENANT_B for c in b_claims)


# ---------------------------------------------------------------- slice K


def test_conflicts_are_explicit_and_open_until_resolved() -> None:
    state = new_state()
    seed(state)
    found = conflicts(state, TENANT_A, OWNER_A)

    assert found
    for conflict in found:
        assert conflict["status"] == "open"
        assert conflict["description"]
        assert conflict["claim_ids"]


def test_coverage_links_every_concept_to_a_cited_claim() -> None:
    """Slice K coverage: nothing may be asserted without provenance."""
    state = new_state()
    seed(state)
    claim_ids = {str(c.id) for c in state.claims(TENANT_A)}
    for concept in concepts(state, TENANT_A, OWNER_A):
        assert set(concept["claim_ids"]) <= claim_ids
    for conflict in conflicts(state, TENANT_A, OWNER_A):
        assert set(conflict["claim_ids"]) <= claim_ids


# ---------------------------------------------------------------- slice L


def test_editor_queue_is_visible_to_privileged_roles_only() -> None:
    seed_privileged = client.get(
        "/v1/preview/editor/queues",
        headers=editor_headers("editor"),
    )
    assert seed_privileged.status_code == 200
    assert seed_privileged.json()["conflicts"]

    # A plain student must be refused, not merely hidden.
    learner = client.get("/v1/preview/editor/queues", headers=editor_headers("student"))
    assert learner.status_code == 403


def test_conflict_resolution_is_authorized_and_audited() -> None:
    client.post(
        "/v1/preview/sources",
        headers={**BASE, "Idempotency-Key": "m2-audit"},
        json={"title": "Synthetic", "kind": "note", "content": CHEST},
    )
    queue = client.get("/v1/preview/editor/queues", headers=editor_headers("editor"))
    conflict_id = queue.json()["conflicts"][0]["id"]

    denied = client.post(
        f"/v1/preview/editor/conflicts/{conflict_id}/resolve",
        headers=editor_headers("student"),
        json={"resolution": "keep_both"},
    )
    assert denied.status_code == 403

    resolved = client.post(
        f"/v1/preview/editor/conflicts/{conflict_id}/resolve",
        headers=editor_headers("editor"),
        json={"resolution": "keep_both"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_admin_overview_requires_an_admin_role() -> None:
    assert (
        client.get("/v1/preview/admin/overview", headers=editor_headers("org_admin")).status_code
        == 200
    )
    assert (
        client.get("/v1/preview/admin/overview", headers=editor_headers("editor")).status_code
        == 403
    )


def test_editor_authority_does_not_cross_tenants() -> None:
    other = {
        "x-user-id": "10000000-0000-0000-0000-00000000000b",
        "x-tenant-id": "30000000-0000-0000-0000-00000000000b",
        "x-role": "superadmin",
    }
    client.post(
        "/v1/preview/sources",
        headers={**BASE, "Idempotency-Key": "m2-tenant-a"},
        json={"title": "Synthetic A", "kind": "note", "content": CHEST},
    )
    queue = client.get("/v1/preview/editor/queues", headers=editor_headers("editor"))
    conflict_id = queue.json()["conflicts"][0]["id"]

    # Even a superadmin in another tenant must not resolve this tenant's conflict.
    crossed = client.post(
        f"/v1/preview/editor/conflicts/{conflict_id}/resolve",
        headers=other,
        json={"resolution": "keep_both"},
    )
    assert crossed.status_code == 404


@pytest.mark.parametrize("role", ["learner", "admin", "EDITOR", "super_admin", "root"])
def test_only_the_declared_role_vocabulary_is_accepted(role: str) -> None:
    """An unrecognised role must be rejected outright, not coerced to a default."""
    assert client.get("/v1/preview/editor/queues", headers=editor_headers(role)).status_code == 400


@pytest.mark.parametrize("headers", [{**BASE}, {**BASE, "x-role": ""}])
def test_an_absent_or_blank_role_header_defaults_to_unprivileged(
    headers: dict[str, str],
) -> None:
    """No role must never become an accidental privilege grant."""
    assert client.get("/v1/preview/editor/queues", headers=headers).status_code == 403


def test_resolving_an_unknown_conflict_is_a_404() -> None:
    missing = UUID("40000000-0000-0000-0000-0000000000ff")
    assert (
        client.post(
            f"/v1/preview/editor/conflicts/{missing}/resolve",
            headers=editor_headers("editor"),
            json={"resolution": "keep_both"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("resolution", ["keep-both", "delete-everything", "", "ACCEPT_A"])
def test_only_declared_resolution_values_are_accepted(resolution: str) -> None:
    """The resolution vocabulary is closed; anything else must be rejected."""
    queue = client.get("/v1/preview/editor/queues", headers=editor_headers("editor"))
    conflict_id = queue.json()["conflicts"][0]["id"]

    assert (
        client.post(
            f"/v1/preview/editor/conflicts/{conflict_id}/resolve",
            headers=editor_headers("editor"),
            json={"resolution": resolution},
        ).status_code
        == 422
    )


def test_resolution_body_rejects_unknown_fields() -> None:
    queue = client.get("/v1/preview/editor/queues", headers=editor_headers("editor"))
    conflict_id = queue.json()["conflicts"][0]["id"]

    assert (
        client.post(
            f"/v1/preview/editor/conflicts/{conflict_id}/resolve",
            headers=editor_headers("editor"),
            json={"resolution": "keep_both", "override_rls": True},
        ).status_code
        == 422
    )


def test_knowledge_endpoints_are_tenant_scoped_over_http() -> None:
    client.post(
        "/v1/preview/sources",
        headers={**BASE, "Idempotency-Key": "m2-http-a"},
        json={"title": "Synthetic A", "kind": "note", "content": CHEST},
    )
    other = {
        "x-user-id": "10000000-0000-0000-0000-00000000000b",
        "x-tenant-id": "30000000-0000-0000-0000-00000000000b",
    }
    client.get("/v1/preview/concepts", headers=BASE)
    a_concepts = {c["id"] for c in client.get("/v1/preview/concepts", headers=BASE).json()}
    b_concepts = {c["id"] for c in client.get("/v1/preview/concepts", headers=other).json()}

    assert a_concepts and b_concepts
    assert a_concepts.isdisjoint(b_concepts)
    # The head-only material in tenant B must not surface in tenant A.
    assert HEAD.splitlines()[1] not in {
        c["name"] for c in client.get("/v1/preview/concepts", headers=BASE).json()
    }
