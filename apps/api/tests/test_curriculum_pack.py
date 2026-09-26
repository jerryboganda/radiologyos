"""Curriculum pack v2: loading, validation, node ids, candidates, node mappings (ADR 0023)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from apps.worker.app.knowledge.papers import page_counts
from packages.curriculum.candidates import (
    candidate_listing,
    tags_for,
    topic_candidates,
    validate_node_id,
)
from packages.curriculum.contracts import CurriculumPack, pack_hash
from packages.curriculum.loader import PACK_DIR, load_pack, radiology_pack, system_of
from packages.knowledge.curriculum import node_mapping, system_codes
from packages.knowledge.models import PaperTopicsTree
from pydantic import ValidationError

ORIGINAL_SYSTEMS = (
    "NEURO", "HEAD_NECK", "CHEST", "CARDIOVASCULAR", "GI", "HEPATOBILIARY_PANCREAS", "GU",
    "OBSTETRIC_GYNAECOLOGICAL_US", "MUSCULOSKELETAL", "BREAST", "PAEDIATRICS",
    "EMERGENCY_TRAUMA", "INTERVENTIONAL", "NUCLEAR_MEDICINE", "PHYSICS",
    "RADIATION_SAFETY_CONTRAST",
)


def test_pack_is_a_draft_tree_that_keeps_every_existing_system_code() -> None:
    pack = radiology_pack()
    assert pack.schema_version == 2 and pack.status == "draft_pending_owner_approval"
    assert pack.exam_blueprint is None and all(n.exam_weight is None for n in pack.nodes)
    assert set(ORIGINAL_SYSTEMS) <= set(system_codes())  # existing mappings keep working
    levels = {level: sum(n.level == level for n in pack.nodes)
              for level in ("system", "topic", "subtopic")}
    assert levels["system"] == 17 and levels["topic"] >= 100 and levels["subtopic"] >= 300
    assert all(len(n.code) <= 60 for n in pack.nodes)  # fits curriculum_code columns


def test_every_node_extends_its_parent_code_and_narrows_its_exam_tags() -> None:
    index = {n.code: n for n in radiology_pack().nodes}
    for node in index.values():
        if node.level in ("topic", "subtopic"):
            parent = index[node.parent_code or ""]
            assert node.code.startswith(parent.code + ".")
            assert set(node.exams) <= set(parent.exams)
    assert "frcr_2a" not in index["PHYSICS"].exams  # FRCR physics is Part 1, not a target
    assert "imm" not in index["INTERVENTIONAL"].exams


def test_pack_hash_is_stable_and_content_bound() -> None:
    pack = radiology_pack()
    assert pack_hash(pack) == pack_hash(load_pack())
    changed = pack.model_copy(update={"version": "other"})
    assert pack_hash(changed) != pack_hash(pack)


def _flat(nodes: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"schema_version": 2, "status": "draft_pending_owner_approval", "source": "t",
            "nodes": [{"code": "R", "parent_code": None, "level": "section", "title": "R"},
                      *nodes], **extra}


@pytest.mark.parametrize("nodes", [
    [{"code": "A", "parent_code": "R", "level": "topic", "title": "t", "exams": ["imm"]}],
    [{"code": "A", "parent_code": "R", "level": "system", "title": "s", "exams": ["imm"]},
     {"code": "B.X", "parent_code": "A", "level": "topic", "title": "t", "exams": ["imm"]}],
    [{"code": "A", "parent_code": "R", "level": "system", "title": "s", "exams": ["imm"]},
     {"code": "A.X", "parent_code": "A", "level": "topic", "title": "t", "exams": ["frcr_2a"]}],
    [{"code": "A", "parent_code": "R", "level": "system", "title": "s", "exams": []}],
    [{"code": "A", "parent_code": "R", "level": "system", "title": "s", "exams": ["imm"],
      "exam_weight": 0.5}],
])
def test_invalid_v2_trees_are_rejected(nodes: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        CurriculumPack.model_validate(_flat(nodes))


def test_loader_inherits_exam_tags_and_rejects_bad_files(tmp_path: Path) -> None:
    manifest = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    (tmp_path / "pack.json").write_text(json.dumps({**manifest, "systems": ["x.json"]}), "utf-8")
    system = {"code": "X", "title": "X", "exams": ["imm", "frcr_2a"],
              "topics": [{"code": "T", "title": "T", "subtopics": {"S": "S"}}]}
    (tmp_path / "x.json").write_text(json.dumps(system), "utf-8")
    pack = load_pack(tmp_path)
    assert [n.code for n in pack.nodes] == ["RADIOLOGY", "X", "X.T", "X.T.S"]
    assert pack.nodes[-1].exams == ("imm", "frcr_2a")
    system["topics"][0]["exams"] = ["fcps2_toacs"]  # type: ignore[index]
    (tmp_path / "x.json").write_text(json.dumps(system), "utf-8")
    with pytest.raises(ValidationError):
        load_pack(tmp_path)


def test_candidates_filter_by_exam_and_depth() -> None:
    frcr = {c["id"] for c in topic_candidates(["frcr"])}
    imm = {c["id"] for c in topic_candidates(["imm"])}
    assert "PHYSICS.MRI" in imm and "PHYSICS.MRI" not in frcr
    assert "INTERVENTIONAL.VASCULAR.EVAR" in frcr and "INTERVENTIONAL" not in imm
    systems = topic_candidates(None, max_level="system")
    assert {c["level"] for c in systems} == {"system"} and len(systems) == 17
    pe = next(c for c in topic_candidates() if c["id"] == "CHEST.PULM_VASC.PE")
    assert pe["path"] == "Chest > Pulmonary vasculature > Pulmonary embolism"
    assert "CHEST.PULM_VASC.PE | Chest > Pulmonary vasculature" in candidate_listing()
    assert tags_for(["unknown"]) == tags_for(None)
    with pytest.raises(ValueError):
        topic_candidates(None, max_level="section")


def test_node_ids_validate_at_any_depth_with_the_same_review_rule() -> None:
    assert validate_node_id(" chest.pulm_vasc.pe ") == "CHEST.PULM_VASC.PE"
    assert validate_node_id("RADIOLOGY") is None and validate_node_id("CHEST.NOPE") is None
    assert system_of("CHEST.PULM_VASC.PE") == "CHEST"
    for node, system in (("CHEST", "CHEST"), ("CHEST.PULM_VASC", "CHEST"),
                         ("PAEDIATRICS.MSK.DDH", "PAEDIATRICS")):
        high, low = node_mapping(node, 0.7), node_mapping(node, 0.69)
        assert high is not None and low is not None
        assert (high.system, high.node_id, high.status) == (system, node, "accepted")
        assert low.status == "review"
    assert node_mapping("MADE_UP", 0.99) is None


def test_v3_page_counts_key_topics_by_node_id() -> None:
    result = PaperTopicsTree.model_validate({
        "is_exam_paper": True, "exam_target": "frcr", "year": None, "paper_label": "",
        "questions": [
            {"question_no": "1", "curriculum_node_id": "CHEST.PULM_VASC.PE",
             "topic": "PE", "confidence": 0.9},
            {"question_no": "2", "curriculum_node_id": "chest.pulm_vasc.pe",
             "topic": "PE again", "confidence": 0.5},
            {"question_no": "3", "curriculum_node_id": "GI", "topic": "Volvulus",
             "confidence": 0.9},
            {"question_no": "4", "curriculum_node_id": "GI.INVENTED", "topic": "x",
             "confidence": 0.9},
        ],
    })
    assert page_counts(result) == {("CHEST", "CHEST.PULM_VASC.PE"): 2, ("GI", "volvulus"): 1}
