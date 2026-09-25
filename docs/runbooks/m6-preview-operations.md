# M6 preview operations and release-boundary runbook

Status: **Non-release operational seams documented; infrastructure evidence pending**
Scope: load smoke, security scans, backup/restore boundaries, billing/export/delete previews
Related: [ADR 0006](../decisions/0006-non-release-preview-mode.md), [M1 preview runbook](m1-preview.md), [data handling](data-handling.md)

## Scope and limits

This document covers preview-mode operations only. It does not approve production
storage, Stripe configuration, retention periods, backup encryption, restore authority,
or release. Real M6 acceptance requires the protected staging environment and Actions
evidence described in [`m0-staging-acceptance.md`](m0-staging-acceptance.md).

## Load smoke

`evals/load/preview-smoke.js` is a small k6 definition for a disposable local/preview
stack. It checks the web health route and the preview page with synthetic headers. It
must run in GitHub Actions or an approved isolated runner, never on the production VPS.
A passing smoke is not a capacity, latency, or clinical-quality result.

Set `RADBRAIN_PREVIEW_URL` to the disposable preview origin and run k6 with a bounded
scenario. Do not add provider calls, private content, or tenant data to the scenario.

## Security checks

The existing CI workflow runs Ruff, mypy, unit tests, Bandit, pip-audit, npm audit,
Compose validation, live migrations, and the runtime-role RLS proof. Preview additions
must not weaken those gates. Trivy, Semgrep, full dependency review, and staging
browser/security evidence remain required before release.

## Backup and restore boundary

Preview state is process-local and is not a backup target. A real backup design must
record, under a separate approved decision:

- encrypted database snapshots and object-storage versioning;
- point-in-time recovery and measured RPO/RTO;
- tenant-safe restore into quarantine before serving traffic;
- key availability, expiry, access review, and legal-hold handling;
- a restore drill with timings and no cross-tenant verification failure.

No backup, retention, or restore command in this repository should be run against
staging or production without the platform/release owner's approval.

## Billing and data rights

The preview billing route returns mock test-mode status only. Release routes for
`POST /v1/me/export` and `DELETE /v1/me` return `501` until durable jobs, audit, and
purge evidence exist. Never present a preview Markdown export as account export or a
soft-deleted preview source as account deletion.

## Escalation

Stop on cross-tenant output, secret exposure, unexpected provider egress, unapproved
retention behavior, or a failed restore isolation check. Preserve redacted IDs and
run references, notify the security/privacy owner, and follow the incident procedure in
the data-handling runbook.
