# Milestone evidence records

One file per milestone, `mN.md` (M0–M7), records the automated exit evidence for
**one commit SHA** deployed to production (ADR 0008, amended by ADR 0022; scope in
ADR 0034). A record is the acceptance claim for its milestone. Until its record is
complete and every row passed, the milestone is **not accepted**, whatever the code,
CI or the demo shows.

## Rules

- **Same SHA.** Every run and drill in a record belongs to the one deployed SHA in its
  header. A green run for any other SHA does not count and is not listed.
- **Generated, not typed.** The run table comes from `python scripts/evidence_record.py
  <40-char sha>`, pasted as printed. When the deployed SHA was not `main`'s tip at
  dispatch, the script prints "not found" for the deploy and verify rows. Fill those
  run ids in by hand from `gh run list --workflow <file>` and mark them *(manual)*.
- **Pasted, not edited.** Drill and check summaries are pasted exactly as printed.
  A failed line stays in the record, together with the re-run that passed.
- **Redacted.** Ids, counts, statuses, hashes and links only. Never add tokens,
  passwords, DSNs, environment files, dumps, source text, prompts, tenant content,
  private file names or private paths, or screenshots of any of these.
- **Honest gaps.** A check that did not run is written as *not run* with the reason.
  It is never marked passed, and a local run never stands in for an Actions run.
- **Order.** M0 first. A record for M(n+1) is written only after M(n) is accepted.
- Keep each record under 400 lines.

## Record format

Each `mN.md` has these sections, in this order.

1. **Header.** Milestone, verdict (*accepted* / *not accepted* / *pending*), the
   deployed 40-character SHA, the deploy date (UTC), the alembic head, and the
   recorder (the orchestrating session or the owner).
2. **Workflow runs.** The table from `scripts/evidence_record.py`: CI, Build images,
   Deploy production, Verify production RLS, Verify production identity, each with
   run id, status, conclusion and creation time, then its *Same-SHA evidence* line.
   Add the other Actions runs the milestone relies on (for example `E2E`, the load
   check, or a milestone's live proofs inside `CI`), again for the same SHA.
3. **Drill and checks.** The summary of `infra/ops/backup-restore-drill.sh` run on
   the deployed head (checksums, restored and live head, tenant-table count with
   ENABLE + FORCE RLS, extensions, Keycloak realm, RPO, RTO), and the
   `check-compliance.sh` result (resource caps, zero violations). Milestones that do
   not need a drill say so.
4. **Milestone checks.** The rows the milestone's definition of done needs beyond the
   shared table, for example the eval gate (`evals/checks/test_mN_*.py`) and its live
   proofs, recorded model-eval runs (completion-plan G32), and the security
   disposition of open advisories.
5. **Demo.** A link to the five-minute script in [`../demos/`](../demos/), the date
   it was run, on which SHA, and any step that could not run (with its reason, for
   example a missing model credential).
6. **Open limitations.** Known limits and accepted risks, each with a link to its ADR
   or runbook. Put here any critical or high finding that is still open; one open
   critical or high finding means the milestone is not accepted.

## Template

```markdown
# MN evidence — <milestone name>

- Verdict: pending | accepted | not accepted
- SHA: `<40 chars>` · deployed <YYYY-MM-DD HH:MM> UTC · alembic head `<revision>`
- Recorded by: <session or owner> on <YYYY-MM-DD>

## Workflow runs
<output of scripts/evidence_record.py, unedited>

## Drill and checks
<drill summary, unedited> · compliance: <result>

## Milestone checks
| Check | Run / source | Result |
| --- | --- | --- |

## Demo
[demos/mN-….md](../demos/…) · run <date> on `<sha7>` · skipped steps: <none | list>

## Open limitations
- …
```

## Records

| Milestone | Record | Demo | State |
| --- | --- | --- | --- |
| M0 Foundation | [`m0.md`](m0.md) | [`m0-foundation.md`](../demos/m0-foundation.md) | pending the next deploy |
| M1 Library | not started | [`m1-library.md`](../demos/m1-library.md) | waits for M0 |
| M2 Knowledge | not started | [`m2-knowledge.md`](../demos/m2-knowledge.md) | waits for M1 |
| M3 Tutor and retrieval | not started | [`m3-tutor.md`](../demos/m3-tutor.md) | waits for M2 |
| M4 Planner and study loop | not started | [`m4-study-loop.md`](../demos/m4-study-loop.md) | waits for M3 |
| M5 Assessment | not started | [`m5-viva-toacs.md`](../demos/m5-viva-toacs.md), [`m5-results-review.md`](../demos/m5-results-review.md) | waits for M4 |
| M6 Operations | not started | [`m6-operations.md`](../demos/m6-operations.md) | waits for M5 |
| M7 Portability | not started | [`m7-portability.md`](../demos/m7-portability.md) | waits for M6 |
