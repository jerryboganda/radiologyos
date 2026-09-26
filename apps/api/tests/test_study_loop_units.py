"""Pure rules of the daily study loop: session steps, SBA selection, weakness cards,
pace projection, calibration, and the heatmap roll-up (no database, no model)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from packages.study import heatmap, session, weakness
from packages.study.calibration import Rated, calibration
from packages.study.projection import PacePoint, Topic, project, weighted_coverage

NOW = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)


def _plan(**over: Any) -> dict[str, Any]:
    blocks = [
        {"kind": "review", "minutes": 10, "due_cards": 4, "target_cards": 4},
        {"kind": "learn", "minutes": 30, "new_cards": 5,
         "topics": [{"code": "CHEST", "title": "Chest", "minutes": 30, "slots": 1}]},
        {"kind": "test", "minutes": 15, "questions": 10, "topics": ["CHEST"],
         "weak_topics": ["NEURO"]},
        {"kind": "viva", "minutes": 5, "topics": ["CHEST"]},
    ]
    return {"blocks": blocks, "priorities": [{"code": "CHEST", "title": "Chest"}], **over}


def _inputs(**over: Any) -> session.SessionInputs:
    base: dict[str, Any] = {
        "plan": _plan(), "card_ids": ["c1", "c2"], "topic": {"code": "CHEST", "title": "Chest"},
        "chunk_ids": ["k1", "k2"], "figure_ids": ["f1"],
        "candidates": [session.SbaCandidate(f"q{i}", "CHEST" if i < 8 else "NEURO")
                       for i in range(14)],
        "retests": [], "viva": session.VivaChoice("graded", question_id="v1"), "seed": 7}
    return session.SessionInputs(**{**base, **over})


def test_steps_follow_the_spec_order_and_drop_empty_blocks() -> None:
    steps = session.build_steps(_inputs())
    assert [s["kind"] for s in steps] == ["review", "learn", "test", "viva"]
    assert [s["step_no"] for s in steps] == [1, 2, 3, 4]
    assert steps[1]["payload"]["chunk_ids"] == ["k1", "k2"]
    assert steps[2]["payload"]["time_limit_minutes"] == 15  # 10 SBA x 1.5 min
    bare = session.build_steps(_inputs(card_ids=[], chunk_ids=[], viva=None))
    assert [s["kind"] for s in bare] == ["test"] and bare[0]["step_no"] == 1
    assert session.build_steps(_inputs(card_ids=[], chunk_ids=[], viva=None,
                                       candidates=[])) == []


def test_sba_block_is_deterministic_and_mixes_today_and_weak_topics() -> None:
    first = session.build_steps(_inputs())[2]["payload"]["question_ids"]
    assert first == session.build_steps(_inputs())[2]["payload"]["question_ids"]
    assert len(first) == 10 and len(set(first)) == 10
    chest = [q for q in first if int(q[1:]) < 8]
    assert len(chest) == 6  # 60 % from today's topics
    assert {"q8", "q9", "q10", "q11", "q12", "q13"} & set(first)  # weak NEURO fill the rest


def test_retests_come_first_capped_at_forty_percent() -> None:
    retests = [session.Retest(f"e{i}", f"q{i}") for i in range(8)]
    retests.append(session.Retest("gone", "retired-question"))
    ids, events = session.select_sba(_inputs(retests=retests), 10)
    assert ids[:4] == ["q0", "q1", "q2", "q3"] and events == ["e0", "e1", "e2", "e3"]
    assert "retired-question" not in ids


def test_never_attempted_questions_are_preferred() -> None:
    fresh = session.SbaCandidate("new", "CHEST", None)
    stale = session.SbaCandidate("old", "CHEST", 30.0)
    recent = session.SbaCandidate("recent", "CHEST", 0.5)
    ids, _ = session.select_sba(_inputs(candidates=[recent, stale, fresh]), 2)
    assert ids == ["new", "old"]


def test_focus_topic_uses_generic_subtree_matching() -> None:
    nodes = [heatmap.Node("R", None, "section", "R"), heatmap.Node("CHEST", "R", "system", "C"),
             heatmap.Node("CHEST.ILD", "CHEST", "topic", "ILD"),
             heatmap.Node("CHEST.ILD.UIP", "CHEST.ILD", "subtopic", "UIP")]
    parent_of = heatmap.parents(nodes)
    deep = session.SbaCandidate("deep", "CHEST.ILD.UIP")
    ids, _ = session.select_sba(_inputs(
        candidates=[session.SbaCandidate("other", "NEURO"), deep],
        within=lambda code, root: heatmap.within(code, root, parent_of)), 1)
    assert ids == ["deep"]
    assert heatmap.subtree("CHEST.ILD", nodes) == ["CHEST.ILD", "CHEST.ILD.UIP"]


def test_summary_counts_answers_minutes_and_freezes_coverage() -> None:
    start = NOW
    steps = [
        {"kind": "review", "status": "done", "minutes": 5, "started_at": start,
         "completed_at": start + timedelta(minutes=4), "result": {}},
        {"kind": "test", "status": "done", "minutes": 15, "started_at": start,
         "completed_at": start + timedelta(hours=3),
         "result": {"answers": {"a": {"correct": True}, "b": {"correct": False}}}},
        {"kind": "viva", "status": "skipped", "minutes": 5, "started_at": None,
         "completed_at": start, "result": {}},
    ]
    summary = session.summarize(steps, reviews=12, weighted_coverage=0.4567)
    assert summary["minutes"] == 4 + 35  # the idle test block is capped at 2 x 15 + 5
    assert (summary["sba_answered"], summary["sba_correct"]) == (2, 1)
    assert summary["steps_done"] == 2 and summary["steps_skipped"] == 1
    assert summary["weighted_coverage"] == 0.4567 and summary["viva_answered"] is False
    assert session.current_step([{"step_no": 1, "status": "done"},
                                 {"step_no": 2, "status": "active"}]) == 2


def test_weakness_card_text_and_timing() -> None:
    question = {"stem": "  Classic   HRCT sign of PAP? ", "topic": "PAP",
                "options": [{"text": "Crazy paving"}, {"text": "Tree in bud"}],
                "answer": {"key": 0}, "explanation": "Septal thickening over GGO."}
    text = weakness.card_text(question)
    assert text["front"] == "Classic HRCT sign of PAP?"
    assert text["back"].startswith("Crazy paving.") and text["topic"] == "PAP"
    assert weakness.card_text({**question, "stem": "x" * 5000})["front"].endswith("…")
    assert weakness.due_at(NOW) - NOW <= timedelta(days=2)
    assert weakness.retest_by(NOW) - NOW == timedelta(days=2)
    assert weakness.card_code(None) == "UNMAPPED" and weakness.card_code("CHEST") == "CHEST"
    assert weakness.card_code("bad code") == "UNMAPPED"
    assert weakness.first_chunk_id([{"kind": "figure"}, {"kind": "chunk", "chunk_id": "c"}]) \
        == "c"
    assert weakness.is_wrong(0.0, 1.0) and not weakness.is_wrong(1.0, 1.0)


def test_projection_needs_history_then_projects_pace() -> None:
    topics = [Topic(0.5, 0.2), Topic(0.5, 0.4)]
    assert weighted_coverage(topics) == pytest.approx(0.3)
    today, exam = date(2026, 9, 26), date(2027, 1, 23)  # 119 days, 89 to the 30-day buffer
    early = project(today, exam, topics, [PacePoint(today, 0.29, 30)])
    assert early["status"] == "insufficient_history" and early["projected_coverage"] is None
    history = [PacePoint(today - timedelta(days=10), 0.2, 60),
               PacePoint(today - timedelta(days=5), 0.25, 60),
               PacePoint(today - timedelta(days=1), 0.29, 60)]
    out = project(today, exam, topics, history)
    assert out["coverage_per_day"] == pytest.approx(0.01)
    assert out["minutes_per_day"] == pytest.approx(12.0)
    assert out["projected_coverage"] == 1.0 and out["status"] == "on_track"
    slow = project(today, exam, topics, [PacePoint(today - timedelta(days=10), 0.29, 60),
                                         PacePoint(today - timedelta(days=1), 0.295, 60)])
    assert slow["status"] == "behind" and slow["projected_coverage"] == pytest.approx(0.419)
    # 0.6 left over 89 days at 0.1/120 coverage per minute -> ~8.1 min/day.
    assert out["needed_minutes_per_day"] == pytest.approx(8.1, abs=0.05)
    assert out["target_days"] == 89 and out["topics_remaining"] == 2
    assert "probability" not in str(out)
    done = project(today, exam, [Topic(1.0, 0.95)], history)
    assert done["status"] == "done" and done["needed_hours_per_day"] == 0.0


def test_calibration_flags_confident_wrong_answers() -> None:
    few = calibration([Rated(3, 0.0)] * 3)
    assert few["verdict"] == "insufficient" and few["confident_wrong"] == 3
    answers = [Rated(3, 0.0)] * 6 + [Rated(3, 1.0)] * 4 + [Rated(1, 1.0)] * 2 + [Rated(9, 1.0)]
    out = calibration(answers)
    assert out["rated"] == 12 and out["verdict"] == "overconfident"
    assert out["bias"] == pytest.approx((10 * 0.9 + 2 * 0.4 - 6) / 12, abs=1e-4)
    high = next(level for level in out["levels"] if level["label"] == "high")
    assert high["answers"] == 10 and high["accuracy"] == 0.4
    assert out["confident_wrong"] == 6 and out["confident_wrong_share"] == 1.0
    fair = calibration([Rated(2, 1.0)] * 13 + [Rated(2, 0.0)] * 7)
    assert fair["verdict"] == "calibrated"
    assert calibration([])["bias"] is None


def test_heatmap_rolls_deep_codes_into_topics_and_handles_flat_systems() -> None:
    nodes = [heatmap.Node("R", None, "section", "Radiology"),
             heatmap.Node("CHEST", "R", "system", "Chest"),
             heatmap.Node("CHEST.ILD", "CHEST", "topic", "ILD"),
             heatmap.Node("CHEST.ILD.UIP", "CHEST.ILD", "subtopic", "UIP"),
             heatmap.Node("CHEST.PE", "CHEST", "topic", "Embolism"),
             heatmap.Node("NEURO", "R", "system", "Neuro")]
    stats = {"CHEST.ILD": heatmap.CodeStats(4, 1, 1.0, 2.0),
             "CHEST.ILD.UIP": heatmap.CodeStats(4, 3),
             "CHEST": heatmap.CodeStats(2, 2), "NEURO": heatmap.CodeStats(5, 0)}
    rows = heatmap.build(nodes, stats, [heatmap.SystemMastery("CHEST", 0.6, "learning", 0.5, 0.7)])
    chest, neuro = rows
    cells = {c["title"]: c for c in chest["cells"]}
    assert cells["ILD"]["material"] == 8 and cells["ILD"]["coverage"] == 0.5
    assert cells["ILD"]["accuracy"] == 0.5 and cells["ILD"]["band"] == "learning"
    assert cells["Embolism"]["coverage"] is None and cells["Embolism"]["band"] == "none"
    assert cells["General"]["coverage"] == 1.0 and chest["band"] == "learning"
    assert [c["title"] for c in neuro["cells"]] == ["All topics"]
    assert neuro["cells"][0]["coverage"] == 0.0 and neuro["mastery"] == 0.0
