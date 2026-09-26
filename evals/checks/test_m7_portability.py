"""M7 eval gate: online-provider boundary, vault export round trip, portability.

Covers the rescoped slice W and slice X of the A-Z queue:
  W  online model providers only. There is no local model and no local-mode
     surface; egress is approved by ADR 0010 and carries no credential
  X  the durable Markdown/Obsidian vault in the account export (ADR 0018,
     ADR 0031): every claim and card cited to source, page, and block; every
     wikilink resolves; the vault reads back to the same row ids

ADR 0031 retired the in-memory preview export that this gate used to test;
these checks run against ``apps/worker/app/datarights/vault*.py``, the code the
export job ships. Row-level tenant isolation of the export is proved live in
``evals/checks/test_data_rights_live.py``.

All content is synthetic.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from apps.api.app.main import app
from apps.worker.app.datarights.vault import VaultRows, escape, render_vault, unescape
from apps.worker.app.datarights.vault_links import read_vault
from evals.checks._vault_support import (
    CHEST,
    EFFUSION,
    GGO,
    HEAD,
    rows_for_user_a,
    rows_for_user_b,
    without_source,
)
from fastapi.testclient import TestClient
from packages.models.routing import RouteName, load_model_routing_config

client = TestClient(app)
MODEL_CONFIG = Path(__file__).resolve().parents[2] / "packages" / "models" / "models.yaml"
HEADERS = {
    "x-user-id": "10000000-0000-0000-0000-00000000000a",
    "x-tenant-id": "30000000-0000-0000-0000-00000000000a",
}
SAFE_PATH = re.compile(r"^vault/(index|(concepts|sources|cards)/[a-z0-9-]+)\.md$")


# ---------------------------------------------------------------- slice W


def test_no_local_model_route_exists() -> None:
    """ADR 0009: online providers only. The local route is gone for good."""
    assert not hasattr(RouteName, "LOCAL")
    assert [route.value for route in RouteName] == ["reason", "extract", "classify", "vision"]


def test_no_local_mode_or_preview_endpoint_exists() -> None:
    for path in ("/v1/preview/local-mode", "/v1/preview/capabilities",
                 "/v1/preview/export/markdown"):
        assert client.get(path, headers=HEADERS).status_code == 404
    assert not [p for p in app.openapi()["paths"] if "preview" in p or "local-mode" in p]


def test_egress_is_approved_only_by_adr_0010_and_carries_no_credential() -> None:
    """ADR 0010 opens egress; the subscription token is never in configuration."""
    config = load_model_routing_config(MODEL_CONFIG)
    assert config.provider_gate.status == "approved"
    assert "0010" in (config.provider_gate.approved_by_adr or "")
    for name in RouteName:
        route = config.routes[name]
        assert route.targets, name
        for target in route.targets:
            assert target.backend == "claude_code", name
            assert target.api_key_env is None, name
            assert target.base_url is None, name


def test_no_undeclared_route_survives_in_the_config_file() -> None:
    """A stale `local:` block left in the YAML would fail the strict schema."""
    config = load_model_routing_config(MODEL_CONFIG)
    assert set(config.routes) == set(RouteName)
    assert "local" not in config.routes


# ---------------------------------------------------------------- slice X


def test_vault_is_markdown_with_front_matter_and_safe_file_names() -> None:
    files = render_vault(rows_for_user_a())
    assert "vault/index.md" in files
    for path, body in files.items():
        assert SAFE_PATH.match(path), path
        assert "\x00" not in body and body.endswith("\n")
        if path != "vault/index.md":
            assert body.startswith("---\nradbrain_id: ")
            assert re.search(r"^# ", body, re.MULTILINE)


def test_every_wikilink_resolves_to_a_file_in_the_vault() -> None:
    index = read_vault(render_vault(rows_for_user_a()))
    assert index.links, "the vault must link concepts, sources, and decks"
    assert index.broken == []


def test_every_claim_and_card_cites_a_real_source_page_and_block() -> None:
    rows = rows_for_user_a()
    files = render_vault(rows)
    index = read_vault(files)
    expected = {(c.source_id, c.page_from, c.page_to, c.blocks) for c in rows.claims}
    expected |= {(c.source_id, c.page_from, c.page_to, ()) for c in rows.cards}
    assert {(c.source_id, c.page_from, c.page_to, c.blocks) for c in index.citations} == expected
    claim_lines = [line for body in files.values() for line in body.splitlines()
                   if "^claim-" in line]
    assert len(claim_lines) == len(rows.claims)


def test_vault_reads_back_to_the_same_row_ids() -> None:
    rows = rows_for_user_a()
    ids = set(read_vault(render_vault(rows)).ids.values())
    assert {s.id for s in rows.sources} | {c.id for c in rows.concepts} <= ids


def test_relations_become_links_between_concept_files() -> None:
    files = render_vault(rows_for_user_a())
    ggo = next(body for path, body in files.items() if path.startswith("vault/concepts/ground"))
    assert "## Related" in ggo
    assert f"associated\\_with: [[concepts/pleural-effusion-{EFFUSION.hex[:8]}|" in ggo


def test_a_disputed_claim_stays_visible_and_labelled() -> None:
    files = render_vault(rows_for_user_a())
    effusion = next(b for p, b in files.items() if p.startswith("vault/concepts/pleural"))
    assert "Effusions layer on decubitus views. (disputed)" in effusion


def test_vault_is_byte_stable_and_independent_of_row_order() -> None:
    rows = rows_for_user_a()
    shuffled = VaultRows(tuple(reversed(rows.sources)), tuple(reversed(rows.concepts)),
                         tuple(reversed(rows.claims)), tuple(reversed(rows.edges)),
                         tuple(reversed(rows.cards)))
    first = render_vault(rows)
    assert render_vault(rows) == first
    assert render_vault(shuffled) == first


def test_a_deleted_source_leaves_the_vault_with_its_orphaned_concepts() -> None:
    rows = rows_for_user_a()
    files = render_vault(without_source(rows, CHEST))
    joined = "\n".join(files.values())
    assert CHEST.hex[:8] not in joined
    assert GGO.hex[:8] not in joined and EFFUSION.hex[:8] not in joined
    # The card survives as a note, but its citation says the source is gone.
    assert "Source: deleted source, p. 2" in joined
    assert read_vault(files).broken == []


def test_reimporting_the_same_rows_reproduces_the_same_vault() -> None:
    rows = rows_for_user_a()
    renamed = replace(rows, sources=tuple(replace(s, title="Renamed notes") for s in rows.sources))
    before, after = render_vault(rows), render_vault(renamed)
    assert render_vault(rows_for_user_a()) == before
    # A title change renames the source file, and every link follows it.
    assert read_vault(after).broken == []
    assert set(read_vault(after).ids.values()) == set(read_vault(before).ids.values())


def test_another_users_knowledge_never_appears() -> None:
    joined = "\n".join(render_vault(rows_for_user_a()).values())
    for foreign in (HEAD, *(c.id for c in rows_for_user_b().concepts)):
        assert foreign.hex[:8] not in joined and str(foreign) not in joined
    assert "subarachnoid" not in joined.lower()


def test_an_empty_account_still_exports_a_valid_vault() -> None:
    files = render_vault(VaultRows())
    assert list(files) == ["vault/index.md"]
    assert files["vault/index.md"].count("(none yet)") == 3
    assert read_vault(files).broken == []


# ------------------------------------------------------------ portability


def test_user_text_cannot_forge_links_html_tags_or_block_ids() -> None:
    hostile = "See [[evil]] <script>x</script> #tag %%hidden%% ^forged `code` a|b"
    rows = rows_for_user_a()
    claims = (replace(rows.claims[0], statement=hostile), *rows.claims[1:])
    files = render_vault(replace(rows, claims=claims))
    index = read_vault(files)
    assert index.broken == []
    assert not [t for _, t in index.links if "evil" in t]
    joined = "\n".join(files.values())
    assert "<script>" not in joined and "%%" not in joined and " ^forged" not in joined
    assert unescape(escape(hostile)) == hostile


def test_vault_uses_only_portable_constructs() -> None:
    for body in render_vault(rows_for_user_a()).values():
        for line in body.splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("<", "|", "```")), line
