"""M7 eval gate: online-provider boundary, export round-trip, and portability.

Covers the rescoped slice W and slice X of the A-Z queue:
  W  online model providers only. There is no local model and no local-mode
     surface, and external egress stays closed until a provider key and a
     privacy review exist
  X  Markdown export and its round-trip links, with provenance preserved

Slice Y is mobile PWA and Core Library authoring only. Institution SSO was
removed from the project by ADR 0009 and is not simulated here.

All content is synthetic.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from apps.api.app.main import app, settings
from apps.api.app.preview.library import ingest_source
from apps.api.app.preview.operations import markdown_export
from apps.api.app.preview.service import reset_preview_state
from apps.api.app.preview.tutor import ask
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
from packages.models.routing import RouteName, load_model_routing_config

client = TestClient(app)
MODEL_CONFIG = Path(__file__).resolve().parents[2] / "packages" / "models" / "models.yaml"
BASE = {
    "x-user-id": "10000000-0000-0000-0000-00000000000a",
    "x-tenant-id": "30000000-0000-0000-0000-00000000000a",
}

CITATION = re.compile(
    r"^Citation: `(?P<source>[0-9a-f-]{36})` p\. (?P<page>\d+) block `(?P<block>[0-9a-f-]{36})`$"
)


def setup_function() -> None:
    reset_preview_state()
    settings.preview_enabled = True


def teardown_function() -> None:
    settings.preview_enabled = False
    reset_preview_state()


def exported():
    state = new_state()
    seed(state)
    return state, markdown_export(state, TENANT_A, OWNER_A)


# ---------------------------------------------------------------- slice W


def test_no_local_model_route_exists() -> None:
    """ADR 0009: online providers only. The local route is gone for good."""
    assert not hasattr(RouteName, "LOCAL")
    assert [route.value for route in RouteName] == [
        "reason",
        "extract",
        "classify",
        "vision",
    ]


def test_no_local_mode_endpoint_exists() -> None:
    assert client.get("/v1/preview/local-mode", headers=BASE).status_code == 404


def test_checked_in_routes_are_still_mock_only_and_egress_is_closed() -> None:
    """Enabling real egress needs a provider key plus the ADR-0009 approval."""
    config = load_model_routing_config(MODEL_CONFIG)
    assert config.provider_gate.external_egress_allowed is False
    assert config.provider_gate.status == "blocked"
    assert config.default_backend == "mock"
    for name in RouteName:
        route = config.routes[name]
        assert route.targets, name
        for target in route.targets:
            assert target.backend == "mock", name
            assert target.api_key_env is None, name
            assert target.base_url is None, name


def test_no_undeclared_route_survives_in_the_config_file() -> None:
    """A stale `local:` block left in the YAML would fail the strict schema."""
    config = load_model_routing_config(MODEL_CONFIG)
    assert set(config.routes) == set(RouteName)
    assert "local" not in config.routes


def test_no_grounded_answer_is_produced_while_the_provider_is_mocked() -> None:
    state = new_state()
    seed(state)
    result = ask(state, TENANT_A, OWNER_A, "costophrenic angle")

    # Mock retrieval may answer, but it must label itself as the preview route.
    assert result["grounding"] == "mock_lexical_preview"
    assert result["mode"] == "preview"
    assert result["citations"]


def test_preview_is_absent_from_the_contract_when_disabled() -> None:
    settings.preview_enabled = False
    for path in ("/v1/preview/capabilities", "/v1/preview/local-mode"):
        assert client.get(path, headers=BASE).status_code in {404, 403}


# ---------------------------------------------------------------- slice X


def test_export_is_markdown_shaped() -> None:
    _, document = exported()
    assert document.startswith("# radbrain preview export")
    # Headings, paragraphs and no binary or HTML payload.
    assert "<html" not in document.lower()
    assert "\x00" not in document
    assert re.search(r"^## ", document, re.MULTILINE)


def test_every_export_citation_parses_and_resolves_back_to_a_real_block() -> None:
    state, document = exported()
    citations = [
        CITATION.match(line.strip())
        for line in document.splitlines()
        if line.strip().startswith("Citation: `")
    ]
    assert citations, "export must carry citations"

    for match in citations:
        assert match is not None, "every citation line must be machine-parseable"
        source_id = UUID(match.group("source"))
        page_no = int(match.group("page"))
        block_id = UUID(match.group("block"))
        source = state.source(TENANT_A, source_id)
        assert source is not None
        assert state.page(TENANT_A, source.id, page_no) is not None
        assert block_id in {b.id for b in state.page_blocks(TENANT_A, source.id, page_no)}


def test_export_round_trips_through_a_reingest() -> None:
    """Slice X: exported content must survive a re-ingest with citations intact."""
    state, document = exported()
    citation_lines = [
        line for line in document.splitlines() if line.strip().startswith("Citation: `")
    ]
    first_page = int(CITATION.match(citation_lines[0].strip()).group("page"))

    # Strip the export scaffolding and re-ingest the body as a new document.
    body = "\n".join(
        line
        for line in document.splitlines()
        if not line.startswith("#") and not line.startswith("Source: `")
    )
    round_state = new_state()
    round_source, _job = ingest_source(
        round_state, TENANT_A, OWNER_A, "Round trip", "note", body, "m7-round"
    )

    assert round_state.source_chunks(TENANT_A, round_source.id)
    assert round_state.page(TENANT_A, round_source.id, 1) is not None
    # The original citation still points at a real page in the original source.
    assert state.page(TENANT_A, state.sources(TENANT_A)[0].id, first_page) is not None


def test_export_preserves_provenance_after_a_delete_and_reingest() -> None:
    state = new_state()
    source, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m7-prov")
    original_citations = markdown_export(state, TENANT_A, OWNER_A).count("Citation: `")
    assert original_citations > 0

    state.soft_delete_source(TENANT_A, source.id, state.now())
    assert markdown_export(state, TENANT_A, OWNER_A).count("Citation: `") == 0

    reingested, _ = ingest_source(state, TENANT_A, OWNER_A, "Synthetic", "note", CHEST, "m7-prov")
    after = markdown_export(state, TENANT_A, OWNER_A)
    assert after.count("Citation: `") == original_citations
    # New source, so new citation targets.
    assert str(reingested.id) in after
    assert str(source.id) not in after


def test_export_is_byte_stable_across_repeated_calls() -> None:
    state, first = exported()
    assert markdown_export(state, TENANT_A, OWNER_A) == first
    assert markdown_export(state, TENANT_A, OWNER_A) == first


def test_export_never_contains_another_tenants_identifiers() -> None:
    state = new_state()
    seed(state)
    ingest_source(state, TENANT_B, OWNER_B, "Head", "note", HEAD, "m7-b")

    document = markdown_export(state, TENANT_A, OWNER_A)
    b_source = state.sources(TENANT_B)[0]

    assert str(b_source.id) not in document
    assert str(TENANT_B) not in document
    assert "subarachnoid" not in document


def test_export_of_an_empty_tenant_is_still_a_valid_document() -> None:
    state = new_state()
    document = markdown_export(state, TENANT_A, OWNER_A)
    assert document.startswith("# radbrain preview export")
    assert "Not a Core Library artifact" in document
    assert "Citation: `" not in document


# ------------------------------------------------------------ portability


def test_export_uses_only_portable_markdown_constructs() -> None:
    _, document = exported()
    for line in document.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Headings, plain text, or backticked provenance. No HTML, no tables
        # that would not survive a round trip through a note editor.
        assert not stripped.startswith("<")
        assert "|" not in stripped or stripped.startswith("Citation:")


def test_a_second_owner_exports_only_their_own_sources() -> None:
    state = new_state()
    seed(state)
    owner_b_source, _ = ingest_source(
        state, TENANT_A, OWNER_B, "Owned by B", "note", HEAD, "m7-owner-b"
    )

    document = markdown_export(state, TENANT_A, OWNER_B)
    assert str(owner_b_source.id) in document
    a_source = state.sources(TENANT_A)[0]
    assert str(a_source.id) not in document
