"""Unit tests for scripts/evidence_record.py with a fake ``gh`` runner."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SHA = "a" * 40
OTHER = "b" * 40


def _load() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "evidence_record.py"
    spec = importlib.util.spec_from_file_location("evidence_record", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["evidence_record"] = module
    spec.loader.exec_module(module)
    return module


er = _load()


def _run(run_id: int, sha: str, created: str, conclusion: str = "success") -> dict[str, object]:
    return {
        "databaseId": run_id, "status": "completed", "conclusion": conclusion,
        "createdAt": created, "headSha": sha, "url": f"https://example.invalid/runs/{run_id}",
        "event": "push",
    }


class FakeGh:
    def __init__(self, by_workflow: dict[str, list[dict[str, object]]]) -> None:
        self.by_workflow = by_workflow
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> str:
        self.calls.append(list(argv))
        workflow = argv[argv.index("--workflow") + 1]
        return json.dumps(self.by_workflow.get(workflow, []))


def _all_green() -> FakeGh:
    return FakeGh({
        workflow: [_run(10 + i, SHA, f"2026-09-26T0{i}:00:00Z")]
        for i, (_, workflow) in enumerate(er.EVIDENCE_WORKFLOWS)
    })


def test_parse_picks_newest_run_for_the_sha_only() -> None:
    payload = json.dumps([
        _run(1, SHA, "2026-09-26T01:00:00Z", "failure"),
        _run(2, SHA, "2026-09-26T03:00:00Z"),
        _run(3, OTHER, "2026-09-26T05:00:00Z"),
    ])
    evidence = er.parse_runs("CI", SHA, payload)
    assert (evidence.run_id, evidence.conclusion, evidence.passed) == (2, "success", True)


def test_parse_reports_missing_run() -> None:
    evidence = er.parse_runs("CI", SHA, json.dumps([_run(3, OTHER, "2026-09-26T05:00:00Z")]))
    assert evidence.run_id is None and evidence.status == "not found" and not evidence.passed
    assert er.parse_runs("CI", SHA, "").run_id is None


def test_in_progress_run_is_not_green() -> None:
    run = _run(4, SHA, "2026-09-26T05:00:00Z")
    run.update(status="in_progress", conclusion=None)
    evidence = er.parse_runs("CI", SHA, json.dumps([run]))
    assert evidence.conclusion == "" and not evidence.passed


def test_collect_queries_every_evidence_workflow_by_commit() -> None:
    fake = _all_green()
    evidence = er.collect(SHA, fake, repo="owner/repo")
    assert [item.label for item in evidence] == [label for label, _ in er.EVIDENCE_WORKFLOWS]
    for call in fake.calls:
        assert call[:2] == ["run", "list"]
        assert call[call.index("--commit") + 1] == SHA
        assert call[-2:] == ["--repo", "owner/repo"]


def test_collect_rejects_short_or_malformed_sha() -> None:
    with pytest.raises(ValueError):
        er.collect("abc123", _all_green())


def test_main_renders_table_and_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert er.main([SHA], runner=_all_green()) == 0
    out = capsys.readouterr().out
    assert "| Verify production RLS | [13](https://example.invalid/runs/13) |" in out
    assert "**all green**" in out
    partial = _all_green()
    partial.by_workflow["deploy-production.yml"] = []
    assert er.main([SHA], runner=partial) == 1
    assert "| Deploy production | — | not found |" in capsys.readouterr().out
