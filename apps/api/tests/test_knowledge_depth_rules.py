"""Knowledge depth rules without a database or model (ADR 0030).

Synthesis citation checks fail closed; Resolver/Conflict policies; reversible
merge planning; and table parsing.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from packages.knowledge import adjudication as adj
from packages.knowledge.agents import ConceptNote
from packages.knowledge.synthesis import (
    build_prompt,
    check_note,
    claims_hash,
    label_claims,
    note_problem,
    supported,
)
from packages.library.tables import parse_table, plain_text, to_csv, to_html

C1, C2, C3 = uuid4(), uuid4(), uuid4()
CLAIMS: list[dict[str, Any]] = [
    {"id": C1, "status": "active", "importance": 5, "claim_type": "imaging_finding",
     "modality": "HRCT", "statement": "Synthetic PAP shows crazy paving on HRCT.",
     "evidence_span": "crazy paving on HRCT"},
    {"id": C2, "status": "disputed", "importance": 3, "claim_type": "epidemiology",
     "modality": "", "statement": "Synthetic PAP presents at 40 years in men.",
     "evidence_span": "presents at 40 years"},
    {"id": C3, "status": "active", "importance": 4, "claim_type": "differential",
     "modality": "CT", "statement": "Pulmonary oedema also shows crazy paving with effusions.",
     "evidence_span": "oedema also shows crazy paving"},
]


def sentence(text: str, *cites: str) -> dict[str, Any]:
    return {"text": text, "cites": list(cites)}


def note(**sections: Any) -> ConceptNote:
    base: dict[str, Any] = {"definition": [], "imaging": [], "differentials": [],
                            "pearls": [], "pitfalls": []}
    return ConceptNote.model_validate({**base, **sections})


def labels() -> dict[str, Any]:
    return label_claims(CLAIMS)


def test_claims_hash_is_order_free_and_tracks_status_and_text() -> None:
    assert claims_hash(CLAIMS) == claims_hash(list(reversed(CLAIMS)))
    changed = [dict(CLAIMS[0], status="superseded"), *CLAIMS[1:]]
    assert claims_hash(changed) != claims_hash(CLAIMS)
    assert len(claims_hash(CLAIMS)) == 64


def test_labels_rank_by_importance_and_prompt_marks_disputed() -> None:
    labelled = labels()
    assert [labelled[k]["id"] for k in ("C1", "C2", "C3")] == [C1, C3, C2]
    prompt = build_prompt({"name": "PAP", "concept_type": "disease", "aliases": ["PAP"]},
                          labelled, ["Pulmonary oedema"])
    assert "[C3] (epidemiology; DISPUTED by another source)" in prompt
    assert "Linked differentials in the graph: Pulmonary oedema" in prompt


def test_supported_requires_words_numbers_and_negation_from_the_cited_claims() -> None:
    cited = ["Synthetic PAP presents at 40 years in men."]
    assert supported("PAP typically presents at 40 years in men.", cited)
    assert not supported("PAP presents at 60 years in men.", cited)
    assert not supported("PAP does not present in men.", cited)
    assert not supported("Honeycombing and traction bronchiectasis dominate.", cited)


def test_check_note_keeps_cited_supported_sentences_and_drops_the_rest() -> None:
    checked = check_note(note(
        definition=[sentence("Synthetic PAP shows crazy paving on HRCT.", "C1"),
                    sentence("Synthetic PAP affects 90% of smokers.", "C1"),
                    sentence("Crazy paving on HRCT is typical.", "C9"),
                    sentence("Crazy paving on HRCT is typical.", "C1", "C99")],
        imaging=[{"modality": "HRCT",
                  "sentences": [sentence("Crazy paving is seen on HRCT.", "[C1]")]},
                 {"modality": "MRI", "sentences": [sentence("Bright on T2.", "C1")]}],
        differentials=[
            {"name": "Pulmonary oedema",
             "discriminators": [sentence("Oedema also shows crazy paving with effusions.",
                                         "C2")]},
            {"name": "Invented", "discriminators": [sentence("Nothing supports this.", "C1")]}],
    ), labels(), {"pulmonary edema": "ddx-id"})
    assert checked.kept == 3 and checked.dropped == 5
    assert [s["text"] for s in checked.body["definition"]] == [
        "Synthetic PAP shows crazy paving on HRCT."]
    assert checked.body["imaging"] == [{"modality": "HRCT", "sentences": [
        {"text": "Crazy paving is seen on HRCT.", "claim_ids": [str(C1)]}]}]
    [ddx] = checked.body["differentials"]
    assert ddx["name"] == "Pulmonary oedema" and ddx["concept_id"] == "ddx-id"
    assert set(checked.claim_ids) == {str(C1), str(C3)}


def test_note_problem_is_the_fail_closed_quality_gate() -> None:
    empty = note(pearls=[sentence("Entirely unrelated statement here.", "C1")])
    assert note_problem(empty, labels()) == "no_supported_sentences"
    assert check_note(empty, labels()).kept == 0
    mostly = note(pearls=[sentence("Synthetic PAP shows crazy paving on HRCT.", "C1"),
                          sentence("Unrelated one.", "C1"), sentence("Unrelated two.", "C1")])
    assert note_problem(mostly, labels()) == "mostly_unsupported"
    good = note(pearls=[sentence("Synthetic PAP shows crazy paving on HRCT.", "C1")])
    assert note_problem(good, labels()) is None


def test_resolver_and_conflict_policies() -> None:
    assert adj.resolver_action("merge", 0.9) == "merge"
    assert adj.resolver_action("merge", 0.84) == "review"
    assert adj.resolver_action("parent_child", 0.95) == "distinct"
    assert adj.resolver_action("distinct", 0.5) == "review"
    assert adj.conflict_action("context", 0.8) == "auto_resolve"
    assert adj.conflict_action("same", 0.79) == "keep_open"
    assert adj.conflict_action("conflict", 0.99) == "keep_open"
    text = adj.conflict_resolution_text("context", "Different ages [A] [B].", "flat bones")
    assert text.startswith("Both valid in context (flat bones). Model rationale:")


def concept(name: str, key: str, aliases: list[str], keys: list[str],
            claims: int, created: str) -> dict[str, Any]:
    return {"id": uuid4(), "name": name, "normalized_name": key, "aliases": aliases,
            "alias_keys": keys, "claim_count": claims, "created_at": created}


def test_merge_plan_adds_only_new_names_and_undo_removes_exactly_those() -> None:
    big = concept("Appendiceal mucocele", "appendiceal mucocele", ["AM"], ["am"], 5, "2026-01")
    small = concept("Mucocele of the appendix", "mucocele of the appendix",
                    ["AM", "mucocoele"], ["am", "mucocele"], 2, "2025-01")
    survivor, merged = adj.choose_survivor(small, big)
    assert survivor is big and merged is small
    aliases, keys = adj.merge_additions(survivor, merged)
    assert aliases == ["Mucocele of the appendix", "mucocoele"]
    assert keys == ["mucocele of the appendix", "mucocele"]
    after = [*big["aliases"], *aliases, "Added later"]
    assert adj.without(after, aliases) == ["AM", "Added later"]
    assert adj.without([*big["alias_keys"], *keys], keys) == big["alias_keys"]
    tie_a = concept("A", "a", [], [], 1, "2026-01")
    tie_b = concept("B", "b", [], [], 1, "2025-01")
    assert adj.choose_survivor(tie_a, tie_b)[0] is tie_b
    assert adj.pair_key("b", "a") == ("a", "b")


def test_pipe_table_with_markdown_separator_becomes_rows() -> None:
    table = parse_table("| Grade | Finding |\n|---|:---:|\n| I | <5 mm & calm |\n| II | 5-10 mm")
    assert table is not None and table.header
    assert table.rows == [["Grade", "Finding"], ["I", "<5 mm & calm"], ["II", "5-10 mm"]]
    assert (table.n_rows, table.n_cols) == (3, 2)
    assert to_csv(table).splitlines()[1] == "I,<5 mm & calm"
    html = to_html(table)
    assert "<th>Grade</th>" in html and "&lt;5 mm &amp; calm" in html and "<script" not in html
    assert plain_text(table).splitlines()[0] == "Grade | Finding"


def test_tab_and_space_columns_pad_ragged_rows_and_prose_is_not_a_table() -> None:
    tabbed = parse_table("Bosniak\tEnhancement\tAction\nI\tnone")
    assert tabbed is not None and tabbed.rows[1] == ["I", "none", ""]
    spaced = parse_table("Sign      Meaning\nTarget    Intussusception")
    assert spaced is not None and spaced.rows[1] == ["Target", "Intussusception"]
    assert parse_table("A single paragraph of prose.\nAnother line of prose.") is None
    assert parse_table("") is None
    injected = parse_table('| <img src=x onerror=alert(1)> | b |')
    assert injected is not None and "<img" not in to_html(injected)
