"""Evidence-span enforcement, name normalisation, and entity resolution."""

from __future__ import annotations

from uuid import uuid4

from packages.knowledge.evidence import (
    evidence_pages,
    filter_extraction,
    locate_blocks,
    only_questions,
    verify_span,
)
from packages.knowledge.models import KnowledgeExtraction
from packages.knowledge.resolution import Candidate, decide, merged_aliases
from packages.knowledge.text import alias_keys, normalize_name, trigram_similarity

CHUNK = (
    "Usual interstitial pneumonia (UIP) shows basal, subpleural reticulation with\n"
    "honeycombing and traction bronchiectasis on HRCT. Ground-glass opacity is not a\n"
    "dominant feature of UIP."
)


def _extraction(*spans: str) -> KnowledgeExtraction:
    return KnowledgeExtraction.model_validate({
        "concepts": [{"name": "Usual interstitial pneumonia", "type": "disease",
                      "aliases": ["UIP"]}],
        "claims": [
            {"concept": "Usual interstitial pneumonia", "type": "imaging_finding",
             "text": span, "evidence_span": span, "importance": 4,
             "modality": "HRCT"}
            for span in spans
        ],
        "relations": [{"src": "Honeycombing", "dst": "Usual interstitial pneumonia",
                       "relation": "sign_of"}],
    })


def test_verbatim_span_is_accepted_and_paraphrase_rejected() -> None:
    assert verify_span("basal, subpleural reticulation", CHUNK) == "basal, subpleural reticulation"
    assert verify_span("subpleural basal reticulation", CHUNK) is None
    assert verify_span("Ground-glass opacity is a dominant feature", CHUNK) is None


def test_span_tolerates_only_line_wrapping_whitespace() -> None:
    wrapped = "reticulation with honeycombing"
    assert wrapped not in CHUNK
    assert verify_span(wrapped, CHUNK) == "reticulation with honeycombing"


def test_trivially_short_spans_are_rejected() -> None:
    assert verify_span("UIP", CHUNK) is None
    assert verify_span("   ", CHUNK) is None


def test_filter_drops_unsupported_claims_and_dangling_relations() -> None:
    kept = filter_extraction(
        _extraction("traction bronchiectasis on HRCT", "invented upper lobe predominance"),
        CHUNK,
    )
    assert [c.evidence_span for c in kept.claims] == ["traction bronchiectasis on HRCT"]
    assert kept.rejected_claims == 1
    assert kept.relations == [] and kept.rejected_relations == 1


def test_claim_concept_missing_from_concepts_is_added() -> None:
    result = KnowledgeExtraction.model_validate({
        "concepts": [],
        "claims": [{"concept": "Honeycombing", "type": "imaging_finding", "text": "x",
                    "evidence_span": "honeycombing and traction", "importance": 3,
                    "modality": ""}],
        "relations": [],
    })
    kept = filter_extraction(result, CHUNK)
    assert [c.name for c in kept.concepts] == ["Honeycombing"]


def test_locate_blocks_cites_the_block_carrying_the_span() -> None:
    blocks = [
        {"page_no": 3, "block_no": 0, "text": "Idiopathic UIP pattern",
         "bbox": [0.1, 0.1, 0.9, 0.2]},
        {"page_no": 3, "block_no": 1, "text": "Basal honeycombing on HRCT.",
         "bbox": [0.1, 0.3, 0.9, 0.4]},
        {"page_no": 4, "block_no": 0, "text": "Unrelated text here", "bbox": [0, 0, 1, 1]},
    ]
    refs = locate_blocks("honeycombing on HRCT", blocks)
    assert refs == [{"page_no": 3, "block_no": 1, "bbox": [0.1, 0.3, 0.9, 0.4]}]
    crossing = locate_blocks("UIP pattern Basal honeycombing", blocks)
    assert {(r["page_no"], r["block_no"]) for r in crossing} == {(3, 0), (3, 1)}


def test_a_span_that_only_asks_questions_supports_nothing() -> None:
    deck = ("PELVIS. • Q1. What examination is this? • Q2. What does line A represent? "
            "Answer. 1. MR pelvimetry. 2. Line A is the obstetric conjugate.")
    assert verify_span("Q2. What does line A represent?", deck) is None
    assert only_questions("Q1. What is the modality used? Q2. What are the findings? Ans.")
    assert verify_span("2. Line A is the obstetric conjugate.", deck)
    assert not only_questions("What is the diagnosis? Pericardial effusion.")


def test_citations_name_the_page_the_evidence_is_on() -> None:
    refs = [{"page_no": 13, "block_no": 2, "bbox": []}]
    assert evidence_pages(refs, 12, 15) == (13, 13)
    assert evidence_pages([], 12, 15) == (12, 15)
    assert evidence_pages([{"page_no": 40, "block_no": 0}], 12, 15) == (12, 15)


def test_normalisation_handles_spelling_eponyms_and_abbreviations() -> None:
    assert normalize_name("Oesophageal Haemorrhage") == normalize_name("esophageal hemorrhage")
    assert normalize_name("Crohn's disease") == normalize_name("Crohn disease")
    assert normalize_name("Paediatric  tumour") == "pediatric tumor"
    assert normalize_name("HRCT") == "high resolution computed tomography"
    assert normalize_name("UIP") == normalize_name("usual interstitial pneumonia")
    assert alias_keys("Usual interstitial pneumonia", ["UIP", "U.I.P."]) == [
        "usual interstitial pneumonia"
    ]


def test_trigram_similarity_matches_pg_trgm_shape() -> None:
    assert trigram_similarity("pneumonia", "pneumonia") == 1.0
    assert trigram_similarity("", "x") == 0.0
    assert 0.5 < trigram_similarity("pneumothorax", "pneumothoraces") < 1.0


def test_resolution_merges_on_alias_or_near_exact_and_separates_otherwise() -> None:
    existing = uuid4()
    pool = [Candidate(existing, "usual interstitial pneumonia", ("usual interstitial pneumonia",))]
    assert decide(["usual interstitial pneumonia"], pool).action == "merge"
    plural = decide([normalize_name("Usual interstitial pneumonias")], pool)
    assert (plural.action, plural.concept_id) == ("merge", existing)
    alias = decide(["uip"], [Candidate(existing, "usual interstitial pneumonia", ("uip",))])
    assert (alias.action, alias.similarity) == ("merge", 1.0)
    distinct = decide(["nonspecific interstitial pneumonia"], pool)
    assert distinct.action == "new" and distinct.concept_id is None and distinct.near is None
    assert decide(["sarcoidosis"], []).action == "new"


def test_resolution_band_between_thresholds_is_flagged_not_merged() -> None:
    existing = uuid4()
    pool = [Candidate(existing, "hepatocellular carcinoma", ())]
    score = trigram_similarity("hepatocelular carcinoma", "hepatocellular carcinoma")
    assert 0.80 <= score < 0.92
    decision = decide(["hepatocelular carcinoma"], pool)
    assert (decision.action, decision.concept_id, decision.near) == ("new", None, existing)


def test_merged_aliases_are_an_ordered_union() -> None:
    aliases, keys = merged_aliases(["UIP"], ["uip"], ["UIP", "usual IP"], ["uip", "usual ip"])
    assert aliases == ["UIP", "usual IP"] and keys == ["uip", "usual ip"]
