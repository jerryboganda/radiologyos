# 0018 — Durable account export and deletion

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0009 (24-month retention), ADR 0011 (personal-first), ADR 0017 (web UI)

`POST /v1/me/export` and `DELETE /v1/me` stop answering 501 and become durable
Celery jobs recorded in the new tenant table `data_jobs` (migration
`20260926_0012`, ENABLE+FORCE RLS, two-tenant runtime-role proof plus a real
export and delete of synthetic users in `evals/checks/test_data_rights_live.py`).
One inventory, `apps/worker/app/datarights/registry.py`, lists every user-owned
table with the predicate selecting one user's rows and how it is erased; a unit
test parses every migration and fails when a table is neither listed nor
explicitly exempt, so a new table cannot escape export or deletion. **Export**
(`radbrain.data_export`) writes a ZIP (JSON per table including embeddings,
cited Markdown of cards and claims, original uploads, figure crops, manifest) to
`tenants/<tenant>/exports/<job>.zip`; `GET /v1/me/exports/{id}/download` streams
it through the API to its owner only (`Cache-Control: no-store`, audited); there
is no presigned URL. Exports expire 7 days after they are built: the hourly beat
task `radbrain.expire_data_exports` finds them through the ids-only SECURITY
DEFINER `app.expired_data_exports` and deletes object then row. **Delete**
requires the typed confirmation `delete my account` and runs idempotent steps in
dependency order — the user's study/tutor/assessment/push rows, then each source
(object prefix first, then the shared per-source purge that also removes
orphaned concepts), then export ZIPs, then identity via the SECURITY DEFINER
`app.erase_user_identity`, which refuses unless the current tenant has a
*running* delete job for that user, deletes `users`, `memberships`, and the
user's audit trail, marks an emptied tenant deleted, and leaves one
content-free `account.erased` audit row plus the delete job's ids-and-counts
row. Sources under `legal_hold` are skipped and reported by id; the user row
then survives only as an anonymous stub (no email, name, or login subject). The
per-source delete now refuses held sources (409). This implements the ADR 0009
purge semantics for a user-initiated delete; the scheduled 24-month purge can
reuse the same job. **Rejected:** presigned download URLs (long-lived bearer
links to personal content), soft-delete only (not an erasure), and granting the
runtime role DELETE on `users`/`audit_log` (broader than one guarded function).
The same change adds the audited curriculum review queue
(`GET /v1/knowledge/mappings`, `POST /v1/knowledge/mappings/{id}/decide`,
`/knowledge/review`) and PWA icons plus an install prompt; the service worker
still caches only the public shell (pinned by `src/lib/service-worker.test.ts`).
