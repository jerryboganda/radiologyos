# Data handling runbook

Status: **Control document; account export and deletion are durable jobs (ADR 0018)**
Scope: local development, private study inputs, tenant data, model egress, Core Library content, and operations
Related: [`M0 runbook`](m0-foundation.md), [RLS ADR](../decisions/0001-tenant-isolation-rls.md), [model-provider gate](../decisions/0002-model-provider-gate.md)

> This is an engineering control, not legal advice. Copyright, privacy, retention,
> patient-data, and Core Library decisions require the designated human owners.

## 1. Non-negotiable boundaries

1. Do not use identifiable patient data in development, tests, demos, evals, issue
   trackers, screenshots, prompts, or documentation. DICOM is rejected in v1.
2. Candidate-owned books and study files remain in their tenant. radbrain never
   redistributes them, and upload-derived drafts never enter the Core Library.
3. Core Library content must be company-authored or licensed with recorded
   provenance and rights. Its origin is an explicit editorial/legal decision.
4. Provider calls that may receive tenant content are blocked until the
   model-provider gate is approved. Default to mock/local processing meanwhile.
5. `ALLOW_UNGROUNDED_DEFAULT=false`; no uncited tutor content is a default path.
6. Telemetry records identifiers and hashes, not source text, figure pixels,
   prompts containing source text, embeddings, credentials, or access tokens.
7. Private object buckets, tenant-prefixed keys, short-lived signed URLs, RLS, and
   tenant-aware caches are required before tenant data is accepted.

Account export and deletion are implemented as durable, audited jobs (section 6,
ADR 0018). Malware scanning, identifier scanning, and production telemetry remain
control obligations, not capabilities to infer from a placeholder.

## 2. Data classification

| Class | Examples | Repository/storage rule |
| --- | --- | --- |
| Public project data | Specs, ADRs, synthetic fixtures, UI copy | May be source controlled after review |
| Credentials/secrets | OIDC client secret, DB/Object-store keys, model keys | Environment/secret manager only; never commit or log |
| Account data | Name, email, time zone, exam date, study activity | Minimize, encrypt, tenant-scope, support export/delete |
| Tenant study content | Uploads, pages, figures, OCR, chunks, claims, questions, chats | Private tenant scope; no cross-tenant cache or read |
| Core Library | Licensed/authored notes, questions, teaching figures | Reserved Core scope with provenance and rights record |
| Operational data | IDs, hashes, timings, token/cost counters, errors | Minimize; no raw content; retention and access controlled |
| Restricted content | Identifiable patient data, credentials, regulated records | Do not ingest; quarantine and escalate if discovered |
| Local private study material | Existing ignored study directories | Never inspect or copy by default; explicit authorization only |

The two ignored root directories named in the repository README are private inputs.
Documentation, test generation, search, indexing, hashing, and uploads must not enter
those directories. Do not record their file names in tickets or chat.

## 3. Local study-material procedure

Use this procedure only when a user has explicitly authorized a specific local test.

### Before access

- Confirm the purpose, permitted files, destination environment, and whether a
  model or external service may receive content.
- Prefer a small, non-original synthetic fixture. Never copy the whole directory.
- Confirm the material contains no identifiable patient data and is not being
  redistributed outside the user's tenant.
- Use a local/private runtime. Do not enable an unapproved cloud route.
- Record only the test ticket and opaque fixture identifier needed for traceability.

### During access

- Read the minimum authorized files. Do not browse unrelated files or metadata.
- Do not print source text into terminal transcripts, logs, screenshots, or chat.
- Do not place source text in fixtures or golden sets. Golden sets require explicit
  rights and de-identification; copied textbook excerpts are not default fixtures.
- Keep originals immutable. Derived pages/crops stay in the tenant object prefix.
- Stop if DICOM, patient identifiers, access credentials, or unexpected sensitive
  content are found. Do not continue to identify the person or institution.

### After access

- Delete ad hoc local copies and generated exports after the test.
- Remove test tenants and object prefixes through approved cleanup procedures.
- Verify Git status and the diff; the private directories must remain ignored and
  absent from the change.
- Record that cleanup completed, without naming or describing private content.


## 4. Ingestion and model boundary

The M1 upload pipeline must enforce this sequence before content becomes available:

1. allowlist and size check (PDF, DOCX, PPTX, PNG, JPEG, TIFF, MD, TXT; target 500 MB);
2. private multipart upload to a tenant-prefixed staging key;
3. checksum/deduplication within the tenant, malware scan, active-content removal,
   image/decompression guard, and DICOM rejection;
4. identifier/patient-content scan and quarantine on a possible hit;
5. parse/render/derive only after checks pass, retaining immutable originals and
   reproducible page/figure artefacts;
6. attach provenance, tenant, retention/legal-hold state, and visible job status;
7. make searchable content available only through tenant-authorized reads.

ClamAV or a scanner can reduce risk but does not prove de-identification. A user
confirmation is not permission to ingest identifiable patient data. Keep quarantined
objects private, inaccessible to workers that expose content, and outside caches.

Source text and images sent to a model are a governed disclosure. Before external
egress, the route must have provider approval, payload minimization, retention/deletion
settings, region/transfer approval, and spend limits. Until then use synthetic data
or an approved local route. Provider prompt caching is off unless its tenant/scope
behavior is reviewed.

Extracted claims, notes, cards, and questions remain tenant-private derived content
with the same access, export, deletion, cache, and legal-hold behavior as their source.
A hash or embedding is personal/derived data when linkable to a tenant or source.

## 5. Core Library boundary

Core content is admitted only through an editorial workflow that records:

- author or licensor, license/contract, permitted audience/region, version, and review;
- provenance for claims, questions, figures, and explanations;
- expiry/takedown contact and legal-hold process;
- confirmation that no upload-derived draft or copyrighted candidate copy was promoted.

Tenant users may read approved Core content, but cannot write it, infer tenant-private
information through it, or use it to bypass provenance. A Core row is not a free pass
for shared caches; only immutable, explicitly Core-scoped artifacts may share.

## 6. Retention, export, deletion, and backups

### Retention

| Data | Kept for | Removed by |
| --- | --- | --- |
| Account content (sources, derived rows, embeddings, objects, study data) | Until the user deletes it; 24 months once the purge is enforced (ADR 0009, ADR 0020) | Per-source delete, account delete, scheduled purge (off by default) |
| Export ZIPs (`tenants/<tenant>/exports/<job>.zip`) and their `data_jobs` rows | 7 days after the ZIP is built | Hourly beat task `radbrain.expire_data_exports` |
| Delete-job rows (`data_jobs`, kind `delete`) | Indefinitely: ids, step, counts, held source ids only | Not removed; this is the deletion evidence |
| `account.erased` audit row | Indefinitely: tenant id, user id, identity outcome only | Not removed |
| Sources under `legal_hold` and their derived rows/objects | Until the hold is lifted | Skipped by every delete path; reported by id |
| Backups | Per the backup runbook window | Expiry of the backup set |

A retention change requires human approval and an ADR.

### Scheduled retention purge (ADR 0020)

- **State:** built but **off** in production. The owner decided this on 2026-09-26.
  The daily beat task `radbrain.retention_purge` returns at once while
  `RETENTION_PURGE_MODE` is unset or `off`.
- **Dry run (read and count only):** run
  `docker exec radiologyos-worker-1 python -m apps.worker.app.datarights.retention`.
  It prints `{"due": n, "purged": 0}` and writes one `retention.dry_run` audit row
  per affected tenant. It cannot delete.
- **Enable:** get the owner's approval first. Then add
  `RETENTION_PURGE_MODE: ${RETENTION_PURGE_MODE:-off}` (and optionally
  `RETENTION_DEFAULT_MONTHS`) to the worker environment, set the value in
  `app.env`, and recreate the worker. Run a dry run first and review the count.
- **Per-tenant override:** set `tenants.settings.retention_months` to a whole
  number of months, or to `0` to exempt the tenant. This is an admin SQL change
  and needs the same approval.
- **Never purged:** sources under `legal_hold`, Core scope or Core tenant
  content, and exempt tenants. The hold is re-checked under a row lock
  immediately before deletion.
- **Evidence:** `SELECT action, target_id, metadata, created_at FROM audit_log
  WHERE action LIKE 'retention.%'` under the tenant context. The live proof is
  `evals/checks/test_retention_live.py` in CI.
- **Rollback:** set the mode back to `off` and recreate the worker. Purged
  sources can be recovered only from a backup taken before the purge.

### Export (`POST /v1/me/export`)

- Settings → *Export my data* queues `radbrain.data_export`. One active export per
  user; repeating the request returns (and re-sends) the active job. Export is
  refused (409) once an account deletion was requested.
- The ZIP holds `data/<table>.json` for every table in
  `apps/worker/app/datarights/registry.py` (the user's own rows, embeddings
  included), `notes/cards.md` and `notes/claims.md` with source and page
  citations, `vault/` (an Obsidian-compatible Markdown vault, ADR 0031: one file
  per concept, source, and card deck under `vault/concepts|sources|cards/`, YAML
  front matter with the row id, `[[wikilinks]]` between concepts and to sources,
  every claim and card citing its source and page, claims also their evidence
  blocks as `(blocks p3-b4)`), `files/<source>/` originals, `figures/<source>/`
  crops, `manifest.json` (includes `vault_files`), and `README.md`. Open the
  `vault/` folder in Obsidian, or read it as plain Markdown; user text is escaped
  so it cannot forge links or HTML. `apps/worker/app/datarights/vault_links.py`
  reads a vault back to row ids, links, and citations. Nothing of another user or tenant is read:
  every query runs under the tenant's RLS context and is filtered to the user.
- Download goes browser → `/settings/exports/{id}` → `GET /v1/me/exports/{id}/download`,
  streamed by the API to the owner only, `Cache-Control: no-store`, audited as
  `data.export_downloaded`. No presigned or public URL exists.

### Account deletion (`DELETE /v1/me`)

- Settings → *Delete my account* requires typing `delete my account`; the API
  enforces the same phrase. The job `radbrain.data_delete` is idempotent and
  resumable: a failure returns it to `queued` with the error class, Celery
  retries with backoff, and re-running any step is safe.
- Steps, in dependency order (`data_jobs.step` shows progress):
  1. `study_rows`: card reviews, attempts, exams, cards, questions, plans,
     profile, tutor messages and threads, topic weights and frequencies, push
     subscriptions, notification settings;
  2. `sources`: for each source not under legal hold, delete the object prefix
     `tenants/<tenant>/sources/<source>/` (original, pages, figures), then the
     per-source purge (pages, blocks, figures, chunks and embeddings, claims,
     edges, conflicts, mappings, knowledge runs, jobs, orphaned concepts);
  3. `exports`: every export ZIP and its row;
  4. `identity`: `app.erase_user_identity` deletes `users`, `memberships`, and
     the user's audit trail, marks an emptied tenant deleted, and writes one
     content-free `account.erased` audit row.
- Legal hold: held sources (and what cascades from them) stay; the job reports
  `held_sources` and `held_source_ids`, and the user row is kept only as an
  anonymous stub (email, name, and login subject erased). Lift the hold, then
  re-run a delete job to finish.
- The registry test (`apps/api/tests/test_data_rights.py`) fails when a
  migration adds a table that is neither registered nor explicitly exempt.
  Register every new user-owned table there with its predicate and erasure.

### Operating checks

- Stuck job: `SELECT id, kind, status, step, error_code, attempts FROM data_jobs`
  under the tenant context; the user can re-request (export) or re-confirm
  (delete) to re-send an active job.
- Proof: `evals/checks/test_data_rights_live.py` exports and deletes synthetic
  users as the runtime role in CI and asserts nothing of theirs remains while
  the other tenant is untouched. A local pass is not release evidence.

Still open: session revocation at the identity provider (the deleted user can no
longer resolve a membership, so API calls fail closed), purge of provider-side
logs, and backup expiry. Backups must be encrypted, access-controlled, tested
for tenant-safe restore, and documented with expiry and RPO/RTO. The product
target is RPO 1 hour and RTO 4 hours, with a quarterly restore drill once
production backups exist.


## 7. Logging, observability, and support access

Logs and traces may include opaque request/trace/job IDs, tenant ID where justified,
model/route/version, token/cost counters, latency, error class, and content hashes.
They must not include source text, full prompts, figure pixels, embeddings, auth
tokens, client secrets, provider keys, signed URLs, or personal study content.

Support access is time-limited and audited. Break-glass database access is not a
substitute for RLS and must not use the runtime application's broad credentials.
Before enabling an observability vendor, apply the same provider decision gate used
for models: region, retention, training/use, redaction, access, and deletion.

## 8. Verification checklist

Before a tenant-data test:

- [ ] synthetic or explicitly authorized, de-identified inputs only
- [ ] provider/egress decision recorded; routes are mock/local if unapproved
- [ ] runtime and migrator database roles are distinct
- [ ] private bucket and `tenants/{tenant_id}/...` key policy verified
- [ ] RLS two-tenant suite passes as the runtime role
- [ ] logs/traces inspected for source text, prompts, secrets, and tokens
- [ ] export/delete/cache cleanup behavior verified (`test_data_rights_live.py` in CI)
- [ ] test tenant and object prefix removed after the test

Useful repository checks (when dependencies and services are available):

```powershell
git status --short
git check-ignore 'Radiology Exam Material' 'Radiology Images'
make check
make rls
```

Expected: both private root paths are ignored, the diff contains no private path or
file content, and required gates pass. A missing tool or unavailable database is a
limitation to report, not a pass.

## 9. Incident and takedown handling

For suspected cross-tenant exposure, patient data, a leaked credential, or private
source egress:

1. stop the affected job/route/provider export and preserve redacted evidence;
2. revoke credentials/signed URLs/sessions and isolate the tenant/object prefix;
3. notify the security/privacy owner; do not investigate by reading more private
   content than necessary;
4. identify affected tenants/records using IDs and audit events, not source dumps;
5. follow approved breach, legal-hold, takedown, and user-notification procedures;
6. record containment, recovery, and follow-up controls without sensitive details.

For copyright takedown, the approved source/legal-hold workflow must hide content
promptly (product target: within one hour) while preserving required evidence.
Never promise a recovery time or deletion result until the owner verifies it.
