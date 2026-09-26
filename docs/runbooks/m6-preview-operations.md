# M6 preview operations and release-boundary runbook

Status: **Non-release operational seams documented; load, scan, and restore evidence recorded**
Scope: load smoke, security scans, backup/restore boundaries, billing/export/delete previews
Gate: `evals/checks/test_m6_ops.py`, `evals/load/production-load.js`
Related: [ADR 0006](../decisions/0006-non-release-preview-mode.md), [M1 preview runbook](m1-preview.md), [backup and restore](backup-restore.md), [data handling](data-handling.md)

## Scope and limits

This document covers preview-mode operations only. It does not approve production
storage, Stripe configuration, retention periods, backup encryption, restore authority,
or release. Real M6 acceptance requires the ADR 0008 evidence chain and milestone-specific
Actions evidence described in the release checklist.

## Load smoke and the production load check

Two distinct k6 definitions, deliberately kept apart:

- `evals/load/preview-smoke.js` targets a disposable local/test stack
  (`RADBRAIN_PREVIEW_URL`). It must run in GitHub Actions or an approved
  isolated runner, never against production.
- `evals/load/production-load.js` targets the deployed production API from
  inside the platform network, because no radbrain port is published on
  `0.0.0.0`. Preview checks are opt-in via `RADBRAIN_LOAD_PREVIEW=1` because
  the preview surface is disabled on the public host; without it the run
  asserts the production read paths, that an anonymous probe of a genuinely
  protected route is refused, that preview routes are absent, and that no 5xx
  occurs. `401/403/404` are treated as expected responses, not failures, so a
  correct refusal never trips the error threshold.

The production run is deliberately small — 5 VUs for 30s — because the owner
asked that the host not be strained. Recorded result: `http_req_failed` rate 0,
400/400 checks passed, p95 26 ms, 100/100 anonymous admin probes refused, 0 5xx.
Raising the VU count is a capacity decision, not a config tweak.

A passing load check is not a capacity, saturation, or clinical-quality result.

## Security checks

CI runs Ruff, mypy, the unit and eval suites, Bandit, pip-audit, npm audit,
Compose validation, live migrations, and the runtime-role RLS proof. Preview
additions must not weaken those gates. Trivy, Semgrep, full dependency review,
and staging browser/security evidence remain required before release.

Unauthenticated behaviour was probed directly on the deployed host: `/v1/me/export`,
`/v1/me`, and `/v1/admin/ping` all return `401 OIDC token required`, and local
preview headers do not bypass that in production. Preview routes return
`404 preview mode is disabled`.

## Backup and restore boundary

Preview state is process-local and is not a backup target. The deployed
database is covered by the shared platform's `bin/backup.sh`, which enumerates
databases dynamically, and the restore drill has been run end to end against a
scratch database. See [`backup-restore.md`](backup-restore.md) for the measured
RPO/RTO, the drill, and what remains uncovered.

Still required under a separate approved decision, and not yet in place:

- off-host replication (nightly dumps are on-box only);
- object-storage versioning and a `mc mirror` for the bucket;
- point-in-time recovery;
- key availability, expiry, access review, and legal-hold handling;
- a tenant-safe restore into quarantine before serving traffic.

No backup, retention, or restore command in this repository should be run against
staging or production without the platform/release owner's approval.

## Billing and data rights

The preview billing route returns `preview_only` mock status and creates no
Stripe customer, checkout, portal, or charge. Real billing is blocked on a
provider decision.

`POST /v1/me/export` and `DELETE /v1/me` are durable, audited jobs (ADR 0018;
procedure in [data handling](data-handling.md) section 6). Never present a preview
Markdown export as account export or a soft-deleted preview source as account
deletion; only `data_jobs` results and the live proof count as evidence.

Preview source delete *is* a full purge of derived artifacts: pages, blocks,
figures, chunks, jobs, and extracted claims are removed, the idempotency key is
released so the content can be re-ingested, and a tombstone is retained for the
audit trail. `evals/checks/test_m6_ops.py` asserts each of those.

## Escalation

Stop on cross-tenant output, secret exposure, unexpected provider egress, unapproved
retention behavior, or a failed restore isolation check. Preserve redacted IDs and
run references, notify the security/privacy owner, and follow the incident procedure in
the data-handling runbook.
