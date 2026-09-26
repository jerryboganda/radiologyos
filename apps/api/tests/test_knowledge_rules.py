"""Conflict heuristics, topic-weight maths, and curriculum review thresholds."""

from __future__ import annotations

import math

import pytest
from apps.worker.app.knowledge.papers import page_counts
from packages.knowledge.conflicts import compare_claims, numbers, topical_overlap
from packages.knowledge.curriculum import mapping_status, system_codes
from packages.knowledge.models import PaperTopics
from packages.knowledge.weights import ALL, Observation, compute_weights


def test_numeric_disagreement_with_same_unit_is_a_conflict() -> None:
    verdict = compare_claims(
        "The normal common bile duct diameter is up to 6 mm in adults",
        "The normal common bile duct diameter is up to 8 mm in adults",
    )
    assert verdict is not None and verdict.kind == "numeric"
    assert "mm" in verdict.description


def test_negation_and_opposed_terms_are_conflicts() -> None:
    negation = compare_claims(
        "Lipid-poor adrenal adenoma shows signal drop on opposed-phase MRI",
        "Lipid-poor adrenal adenoma shows no signal drop on opposed-phase MRI",
    )
    assert negation is not None and negation.kind == "negation"
    opposed = compare_claims(
        "Subacute haematoma is hyperintense on T1-weighted MRI",
        "Subacute haematoma is hypointense on T1-weighted MRI",
    )
    assert opposed is not None and opposed.kind == "opposite_terms"


def test_near_identical_claims_merge_instead_of_conflicting() -> None:
    verdict = compare_claims(
        "Honeycombing is the hallmark of usual interstitial pneumonia on HRCT.",
        "Honeycombing is the hallmark of usual interstitial pneumonia on HRCT",
    )
    assert verdict is not None and verdict.kind == "duplicate"


def test_unrelated_or_compatible_claims_are_left_alone() -> None:
    assert compare_claims(
        "Sarcoidosis shows perilymphatic nodules",
        "Pulmonary alveolar proteinosis shows crazy paving",
    ) is None
    assert compare_claims(
        "Wilms tumour arises from the kidney in children aged 3 years",
        "Wilms tumour arises from the kidney and displaces vessels",
    ) is None


def test_numbers_are_grouped_by_normalised_unit() -> None:
    found = numbers("Peak age 2 years; lesions over 3 cm; T2 bright; 40% bilateral; 5 yrs")
    assert found["years"] == {2.0, 5.0}
    assert found["cm"] == {3.0} and found["%"] == {40.0}
    assert "" not in found or 2.0 not in found.get("", set())
    assert topical_overlap("", "x") == 0.0


def _obs(target: str, code: str, topic: str, paper: str, n: int = 1) -> Observation:
    return Observation(target, code, topic, paper, 2019, n)


def test_system_weights_are_smoothed_and_sum_to_one_per_target() -> None:
    systems = system_codes()
    weights = compute_weights(
        [_obs("imm", "CHEST", "pulmonary embolism", "p1", 3),
         _obs("imm", "NEURO", "glioblastoma", "p1", 1)],
        systems,
    )
    imm = [w for w in weights if w.exam_target == "imm" and w.topic == ""]
    assert len(imm) == len(systems)
    assert math.isclose(sum(w.weight for w in imm), 1.0, abs_tol=1e-5)
    by_code = {w.curriculum_code: w for w in imm}
    total, k = 4, len(systems)
    assert math.isclose(by_code["CHEST"].weight, (3 + 1) / (total + k), abs_tol=1e-6)
    assert math.isclose(by_code["BREAST"].weight, 1 / (total + k), abs_tol=1e-6)
    assert by_code["CHEST"].basis["count"] == 3 and by_code["BREAST"].basis["count"] == 0
    assert by_code["CHEST"].basis["method"] == "laplace_v1"


def test_topic_weights_and_aggregate_target() -> None:
    weights = compute_weights(
        [_obs("imm", "CHEST", "pulmonary embolism", "p1", 2),
         _obs("fcps2_toacs", "CHEST", "pulmonary embolism", "p2", 1),
         _obs("fcps2_toacs", "GI", "intussusception", "p2", 1)],
        system_codes(),
    )
    targets = {w.exam_target for w in weights}
    assert targets == {"imm", "fcps2_toacs", ALL}
    toacs_topics = [w for w in weights if w.exam_target == "fcps2_toacs" and w.topic]
    assert math.isclose(sum(w.weight for w in toacs_topics), 1.0, abs_tol=1e-5)
    pe_all = next(w for w in weights if w.exam_target == ALL and w.topic == "pulmonary embolism")
    assert pe_all.basis["count"] == 3 and pe_all.basis["papers"] == 2


def test_weights_ignore_unknown_codes_and_reject_bad_alpha() -> None:
    assert compute_weights([_obs("imm", "NOT_A_CODE", "x", "p")], system_codes()) == []
    with pytest.raises(ValueError):
        compute_weights([], system_codes(), alpha=0)


def test_classifier_below_threshold_goes_to_review() -> None:
    assert mapping_status("CHEST", 0.95) == "accepted"
    assert mapping_status("CHEST", 0.69) == "review"
    assert mapping_status("MADE_UP", 0.99) is None


def test_page_counts_keep_valid_codes_and_skip_non_papers() -> None:
    result = PaperTopics.model_validate({
        "is_exam_paper": True, "exam_target": "imm", "year": 2019, "paper_label": "",
        "questions": [
            {"question_no": "1", "curriculum_code": "CHEST", "topic": "Pulmonary  Embolism",
             "confidence": 0.9},
            {"question_no": "2", "curriculum_code": "CHEST", "topic": "pulmonary embolism",
             "confidence": 0.8},
            {"question_no": "3", "curriculum_code": "BOGUS", "topic": "x", "confidence": 0.9},
        ],
    })
    assert page_counts(result) == {("CHEST", "pulmonary embolism"): 2}
    cover = result.model_copy(update={"is_exam_paper": False})
    assert page_counts(cover) == {}
