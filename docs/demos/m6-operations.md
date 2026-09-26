# M6 operations — five-minute demo

- Status: a script for a live demo; **not release evidence** (ADR 0008). Billing is out
  of release scope (ADR 0034) and is not shown.
- Data: synthetic material only, never patient images. **Account deletion is shown
  only with a disposable synthetic account**, for example on the local Compose stack
  seeded by `infra/ops/e2e-seed.sh`. Never delete the owner's account to demo it.
- Needs:
  - a signed-in browser (an admin role for the usage cards);
  - an operator shell on the host (`/opt/radiologyos`) for the ops steps;
  - for steps marked **[model]**: the Claude token, so model calls exist in the
    ledger (ADR 0010);
  - for steps marked **[Voyage]**: `VOYAGE_API_KEY` (ADR 0019, ADR 0028).
- Do not enable the retention purge, change `RATE_LIMITS`, or apply MFA during the
  demo. Each needs the owner's OK.
- Related: [data handling](../runbooks/data-handling.md) §6,
  [production deploy](../runbooks/production-deploy.md),
  [backup and restore](../runbooks/backup-restore.md), ADR 0018, ADR 0020, ADR 0032.

## 0:00 — Export my data, with the vault

1. **Settings → Export my data**. Click export. The job appears and moves to *Ready
   to download*. Click **Download ZIP**.
2. Open the ZIP and point out:
   - `data/<table>.json` for every registered table (the user's rows only);
   - `notes/cards.md` and `notes/claims.md` with source and page citations;
   - `vault/` (the M7 vault: `index.md`, `concepts/`, `sources/`, `cards/`);
   - `files/` originals, `figures/` crops, `manifest.json` (with `vault_files`) and
     `README.md`.
3. The link expires after 7 days. The download is streamed by the API to the owner
   only, with `Cache-Control: no-store`. There is no public or presigned URL.

## 0:50 — Rate limits

1. Click export three more times within a minute. The first repeats return the
   active job. The fourth request is refused: the API answers 429 with
   `Retry-After` (the `export` bucket allows a burst of 3 per user).
2. On the host, read `/metrics` (the command is in the production runbook) and find
   `radbrain_rate_limited_total` for the `export` bucket. The labels hold no tenant
   or user id.

## 1:30 — Audit rows and request ids

1. As the operator, list the tenant's latest audit rows:
   `docker exec platform-postgres psql -U platform_admin -d radiologyos -c "SELECT
   action, target_type, target_id, request_id, created_at FROM audit_log WHERE
   tenant_id = '<tenant id>' ORDER BY created_at DESC LIMIT 8"`.
2. Point out the named events (`data.export_requested`, `data.export_downloaded`)
   and the generic `api.post` rows, each with a request id. No row holds a request
   body.
3. Every API response carries `X-Request-ID`. The same id appears on the audit row,
   on `llm_calls` rows, and on the worker log lines of the task it queued.

## 2:10 — Model-usage ledger and alerts

1. **[model]** **Settings → Model calls** (admins): calls per day, agent and backend,
   with outcomes such as `ok`, `usage_limit` and `rejected`.
2. **[Voyage]** **Settings → AI usage**: the embedding meter with the 150M warning
   line and the 195M cap, and a second **Reranking** meter.
3. Explain the alerts: over 5 usage-limit errors in an hour raises an amber
   *model usage limit* alert; the budgets raise amber at 150M and red at 195M. Each
   sends an admin push and shows a banner. **Acknowledge** hides the banner; it
   never raises a cap.

## 2:50 — Readiness and metrics

1. Readiness from inside the api container:
   `{"checks": {"database": "ok", "redis": "ok", "object_storage": "ok"}}`.
2. `/metrics` shows `radbrain_http_requests_total`, the latency histogram,
   `radbrain_job_steps_total` and `radbrain_model_calls_total`.
3. Explain that `/metrics` is not public: any request with a forwarding header or
   from a non-private address gets 404, and with `METRICS_TOKEN` set a bearer token
   is also required.

## 3:20 — Retention purge, dry run only

1. `docker exec radiologyos-worker-1 python -m apps.worker.app.datarights.retention`
   prints `{"due": n, "purged": 0}`. The dry run can only count.
2. It wrote one `retention.dry_run` audit row per affected tenant. The scheduled
   purge stays **off** until the owner enables it (ADR 0020).

## 3:45 — Account deletion (disposable synthetic account only)

1. Signed in as the synthetic user, open **Settings → Delete my account**. Type
   `delete my account` and confirm. The page says deletion is under way.
2. Follow the job's `step`: `study_rows → sources → exports → idp_sessions →
   identity`. The `idp_sessions` outcome is `revoked`, or `not_configured` where the
   Keycloak ops client is not wired.
3. Sign in again with the same user. The API refuses the subject because it has no
   membership. Only a content-free `account.erased` audit row remains.

## 4:20 — Backup and restore drill

1. `/opt/radiologyos/backup-restore-drill.sh` restores the newest nightly dump into a
   scratch database and asserts the checksums, the restored and live alembic head,
   ENABLE + FORCE RLS on every tenant table, the extensions, and the Keycloak realm.
   It prints RPO and RTO, then drops the scratch copy. The live database is only read.
2. `cat /opt/radiologyos/offsite-backup.last-success` shows the time of the last
   off-host copy. Over 26 hours old is an alert.

## 4:45 — Admin MFA

1. `/opt/radiologyos/keycloak/keycloak-mfa.sh --check` reports `browserFlow`, the
   `mfa_required` role and the ops client, and changes nothing.
2. If the rollout is applied, an admin sign-in asks for a 6-digit code; a student's
   does not. Applying it needs the owner present (production runbook).
