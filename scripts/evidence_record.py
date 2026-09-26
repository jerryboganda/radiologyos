#!/usr/bin/env python3
"""Print the release-evidence run table for one commit (ADR 0008, ADR 0022).

For each workflow that carries acceptance evidence, finds the newest run whose
head SHA is the given commit and prints a Markdown table of run id, status,
conclusion, creation time and link. It only calls the ``gh`` CLI with the
caller's existing authentication; no token or secret is read or printed.

Usage:
    python scripts/evidence_record.py <40-char sha> [--repo owner/name]

Limitation: ``Deploy production`` is dispatched from ``main``, so its head SHA is
main's tip at dispatch time. When the deployed SHA was not the tip, the deploy
and verify rows show "not found" and the run ids must be filled in by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - fixed argv to the gh CLI, no shell
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Runner = Callable[[Sequence[str]], str]

EVIDENCE_WORKFLOWS: tuple[tuple[str, str], ...] = (
    ("CI", "ci.yml"),
    ("Build images", "build-images.yml"),
    ("Deploy production", "deploy-production.yml"),
    ("Verify production RLS", "verify-production-rls.yml"),
    ("Verify production identity", "verify-production-oidc.yml"),
)
RUN_FIELDS = "databaseId,status,conclusion,createdAt,headSha,url,event"
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class RunEvidence:
    label: str
    run_id: int | None
    status: str
    conclusion: str
    created_at: str
    url: str

    @property
    def passed(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"


def gh_runner(argv: Sequence[str]) -> str:
    completed = subprocess.run(  # nosec B603 B607 - fixed gh argv, no shell
        ["gh", *argv], check=True, capture_output=True, text=True
    )
    return completed.stdout


def parse_runs(label: str, sha: str, payload: str) -> RunEvidence:
    """Pick the newest run for ``sha`` from ``gh run list --json`` output."""
    runs = [run for run in json.loads(payload or "[]") if run.get("headSha") == sha]
    if not runs:
        return RunEvidence(label, None, "not found", "", "", "")
    newest = max(runs, key=lambda run: str(run.get("createdAt", "")))
    return RunEvidence(
        label=label,
        run_id=int(newest["databaseId"]),
        status=str(newest.get("status", "")),
        conclusion=str(newest.get("conclusion") or ""),
        created_at=str(newest.get("createdAt", "")),
        url=str(newest.get("url", "")),
    )


def collect(sha: str, runner: Runner = gh_runner, repo: str | None = None) -> list[RunEvidence]:
    if not _SHA.match(sha):
        raise ValueError("sha must be a full 40-character lowercase commit SHA")
    evidence = []
    for label, workflow in EVIDENCE_WORKFLOWS:
        argv = ["run", "list", "--workflow", workflow, "--commit", sha,
                "--limit", "20", "--json", RUN_FIELDS]
        if repo:
            argv += ["--repo", repo]
        evidence.append(parse_runs(label, sha, runner(argv)))
    return evidence


def render(sha: str, evidence: Sequence[RunEvidence]) -> str:
    lines = [
        f"Evidence for `{sha}`",
        "",
        "| Workflow | Run | Status | Conclusion | Created (UTC) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in evidence:
        run = f"[{item.run_id}]({item.url})" if item.run_id is not None else "—"
        lines.append(
            f"| {item.label} | {run} | {item.status} | {item.conclusion or '—'} "
            f"| {item.created_at or '—'} |"
        )
    verdict = "all green" if evidence and all(i.passed for i in evidence) else "NOT all green"
    lines += ["", f"Same-SHA evidence: **{verdict}**."]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, runner: Runner = gh_runner) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("sha")
    parser.add_argument("--repo", default=None)
    args = parser.parse_args(argv)
    evidence = collect(args.sha, runner, args.repo)
    print(render(args.sha, evidence))
    return 0 if all(item.passed for item in evidence) else 1


if __name__ == "__main__":
    sys.exit(main())
