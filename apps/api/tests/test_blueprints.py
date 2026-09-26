"""Exam blueprints: defaults, overrides, sizing, mix assembly, negative marking (ADR 0023)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from apps.api.app.assessment.contracts import ExamCreate
from apps.api.tests.test_assessment_depth import _exam, stored
from packages.assessment import exam_result
from packages.assessment.blueprints import (
    MixGroup,
    blueprint_hash,
    effective,
    largest_remainder,
    minutes_for,
    mix_groups,
    packaged,
    scaled_items,
)
from packages.assessment.paper import PaperCandidate, assemble
from pydantic import ValidationError


def test_packaged_defaults_cover_every_exam_and_mark_unverified_facts() -> None:
    blueprints = packaged()
    assert {b.exam_target for b in blueprints.values()} == {
        "fcps2_theory", "fcps2_toacs", "imm", "frcr"}
    assert {b.curriculum_tag for b in blueprints.values()} == {
        "fcps2_theory", "fcps2_toacs", "imm", "frcr_2a", "frcr_2b"}
    frcr = blueprints["frcr_2a"]
    assert frcr.items == {"sba": 120} and frcr.duration_minutes == 180
    assert not frcr.negative_marking.enabled and frcr.pass_mark_percent is None
    assert blueprints["imm_theory"].items == {"sba": 100}
    assert blueprints["imm_theory"].duration_minutes == 120
    assert "duration_minutes" in blueprints["fcps2_toacs"].unverified
    assert all(b.sources for b in blueprints.values())


def test_overrides_are_validated_and_change_the_hash() -> None:
    base = packaged()["imm_theory"]
    changed = effective(base, {"negative_marking": {"enabled": True, "penalty": 0.25},
                               "duration_minutes": 90})
    assert changed.penalty() == 0.25 and changed.duration_minutes == 90
    assert blueprint_hash(changed) != blueprint_hash(base)
    assert blueprint_hash(effective(base, {})) == blueprint_hash(base)
    with pytest.raises(ValueError, match="cannot be overridden"):
        effective(base, {"exam_target": "frcr"})
    bad_mix = {"mix_mode": "fixed", "mix": [{"label": "a", "systems": ["CHEST"], "share": 0.5}]}
    with pytest.raises(ValidationError):
        effective(base, bad_mix)
    with pytest.raises(ValidationError):
        effective(base, {"mix_mode": "fixed", "mix": [
            {"label": "a", "systems": ["NOT_A_SYSTEM"], "share": 1}]})
    with pytest.raises(ValidationError):
        effective(base, {"negative_marking": {"enabled": True, "penalty": 0}})
    with pytest.raises(ValidationError):
        effective(base, {"items": {"sba": 0}})


def test_sizing_scales_counts_and_time_pro_rata() -> None:
    assert largest_remainder(10, [1, 1, 1]) == [4, 3, 3]
    assert largest_remainder(0, [1]) == [0] and largest_remainder(3, [0, 0]) == [0, 0]
    frcr = packaged()["frcr_2a"]
    assert scaled_items(frcr, None) == {"sba": 120} and scaled_items(frcr, 500) == {"sba": 120}
    assert scaled_items(frcr, 30) == {"sba": 30} and minutes_for(frcr, 30) == 45
    mixed = effective(packaged()["fcps2_theory_mcq"], {"items": {"sba": 90, "seq": 10}})
    assert scaled_items(mixed, 20) == {"sba": 18, "seq": 2}


def test_mix_groups_fixed_even_and_weighted() -> None:
    frcr = mix_groups(packaged()["frcr_2a"])
    assert len(frcr) == 6 and abs(sum(g.share for g in frcr) - 1) < 1e-3
    imm = packaged()["imm_theory"]
    even = mix_groups(imm)
    assert "INTERVENTIONAL" not in {g.systems[0] for g in even}  # not tagged for IMM
    assert len({round(g.share, 6) for g in even}) == 1
    weighted = mix_groups(imm, {"CHEST": 3.0, "PHYSICS": 1.0})
    assert [(g.systems[0], g.share) for g in weighted] == [("CHEST", 0.75), ("PHYSICS", 0.25)]
    assert len(mix_groups(imm, {"NOT_TAGGED": 1.0})) == len(even)  # falls back to even


def _candidates(system: str, n: int, item_type: str = "sba",
                tagged: bool = True) -> list[PaperCandidate]:
    return [PaperCandidate(uuid4(), item_type, system, tagged) for _ in range(n)]


def test_assembly_follows_the_mix_and_reports_shortfall() -> None:
    groups = [MixGroup(label="Chest", systems=("CHEST",), share=0.5),
              MixGroup(label="Neuro", systems=("NEURO",), share=0.5)]
    pool = _candidates("CHEST", 10) + _candidates("NEURO", 2) + _candidates("GI", 5)
    picks, report = assemble(pool, {"sba": 10}, groups, seed=1)
    systems = {c.question_id: c.system for c in pool}
    picked = [systems[q] for q, _ in picks]
    assert len(picks) == 10 and len(set(picks)) == 10
    assert picked.count("CHEST") >= 5 and picked.count("NEURO") == 2
    assert report["groups"][1] == {"label": "Neuro", "systems": ["NEURO"],
                                   "requested": 5, "picked": 2}
    assert report["filled_outside_mix"] == 3 and report["shortfall"] == 0
    few, short = assemble(_candidates("CHEST", 3), {"sba": 5}, groups, seed=1)
    assert len(few) == 3 and short["shortfall"] == 2


def test_assembly_prefers_questions_for_the_blueprint_exam_and_splits_types() -> None:
    groups = [MixGroup(label="Chest", systems=("CHEST",), share=1.0)]
    tagged, other = _candidates("CHEST", 3), _candidates("CHEST", 3, tagged=False)
    seq = _candidates("CHEST", 2, "seq")
    picks, report = assemble(other + tagged + seq, {"sba": 3, "seq": 1}, groups, seed=7)
    ids = {q for q, _ in picks}
    assert {c.question_id for c in tagged} <= ids
    assert [t for _, t in picks].count("seq") == 1
    assert report["types"] == {"sba": {"requested": 3, "picked": 3},
                               "seq": {"requested": 1, "picked": 1}}


def test_negative_marking_deducts_only_wrong_sba_answers() -> None:
    right, wrong, blank = stored(), stored(), stored()
    exam = _exam([right, wrong, blank], answers={str(right["id"]): 0, str(wrong["id"]): 1})
    questions: dict[str, Any] = {str(q["id"]): q for q in (right, wrong, blank)}
    plain = exam_result.grade_exam(exam, questions)
    assert (plain["score"], plain["penalty"]) == (1.0, 0.0)
    assert plain["negative_marking"] == {"enabled": False, "penalty": 0.0}
    marked = exam_result.grade_exam(exam, questions, penalty=0.25)
    assert (marked["raw_score"], marked["penalty"], marked["score"]) == (1.0, 0.25, 0.75)
    assert marked["percent"] == 25.0 and marked["negative_marking"]["enabled"] is True
    by_id = {i["question_id"]: i for i in marked["items"]}
    assert by_id[str(wrong["id"])]["score"] == 0.0  # attempts keep a non-negative score
    assert by_id[str(blank["id"])]["penalty"] == 0.0
    refilled = exam_result.fill_item(marked, str(right["id"]), by_id[str(right["id"])])
    assert refilled["score"] == 0.75


def test_exam_create_accepts_a_blueprint_instead_of_a_time_limit() -> None:
    body = ExamCreate(mode="exam", blueprint_id="frcr_2a", blueprint_items=20)
    assert body.time_limit_minutes is None and body.blueprint_id == "frcr_2a"
    with pytest.raises(ValidationError):
        ExamCreate(mode="exam")
    with pytest.raises(ValidationError):
        ExamCreate(mode="practice", blueprint_items=5)
    with pytest.raises(ValidationError):
        ExamCreate(mode="exam", blueprint_id="Bad Id")
