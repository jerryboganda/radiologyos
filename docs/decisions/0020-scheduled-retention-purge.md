# 0020 — Scheduled retention purge, off by default

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0009 (24-month retention), ADR 0011 (personal-first), ADR 0018 (data rights)

**Context.** ADR 0009 sets retention at 24 months, then a purge that is scheduled,
audited, and dry-run capable, and uses the same semantics as a user delete. The
only account today is the owner's personal library. On 2026-09-26 the owner chose
to have the purge built but left switched off.

**Decision.** The daily Celery beat task `radbrain.retention_purge` reads
`RETENTION_PURGE_MODE`, which may be `off` (the default), `dry_run`, or `enforce`.
Unset or unknown values mean `off`, in which case the task opens no database
connection. Due sources come from the new SECURITY DEFINER function
`app.retention_due_sources(at, default_months)` (migration `20260926_0014`). It
returns ids only (tenant, source, months), at most 500 per run, and never returns
Core scope or Core tenant sources, sources under `legal_hold`, or sources of a
tenant whose `tenants.settings.retention_months` is `0`. Any other whole number
in that setting overrides the deployment default, `RETENTION_DEFAULT_MONTHS`
(24). Age is `sources.created_at`.

To see rows despite forced RLS, the definer needs two read-only `SELECT`
policies on `tenants` and `sources`, scoped to `radbrain_migrator` alone. This
follows the resolver pattern already used for `users`, `memberships`, and
`data_jobs`.

- `dry_run` writes one `retention.dry_run` audit row per tenant, holding counts
  only, and deletes nothing.
- `enforce` handles each source in its own tenant transaction. It re-checks the
  hold under `FOR UPDATE`, deletes the object prefix, runs the shared
  `purge_source_rows` (derived rows, embeddings, jobs, orphaned concepts), and
  writes a `retention.source_purged` audit row with `actor_user_id` NULL. A
  crashed run resumes by running again.
- The manual command `python -m apps.worker.app.datarights.retention` can only
  dry-run.

Proof: `evals/checks/test_retention_live.py` runs as the runtime role against
five synthetic tenants (default, exempt, held, override, recent).

**Consequences.** Nothing is deleted until an operator sets
`RETENTION_PURGE_MODE=enforce` in the worker environment. That is a retention
change and needs human approval, recorded against this ADR. A backlog of more
than 500 due sources drains over successive days. Backups taken before a purge
still hold the purged data until the backup set expires; that gap is tracked in
the data-handling runbook.

**Rejected.**
- A new `tenants.retention_months` column: the existing `settings` jsonb avoids
  a schema change on the most sensitive table.
- Reusing the account-delete job: that job erases a user, not an age slice.
- Making `dry_run` the default: it would write audit rows every day for no reader.
- Letting the manual command enforce: that would bypass the off switch.
