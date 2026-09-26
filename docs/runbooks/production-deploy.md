# Production deploy runbook — shared platform VPS

- Status: current
- Scope: deploying radbrain to `185.252.233.186` on the shared platform stack
- Related: [ADR 0007](../decisions/0007-production-on-shared-platform.md),
  [ADR 0006](../decisions/0006-non-release-preview-mode.md),
  [ADR 0008](../decisions/0008-evidence-based-m0-acceptance.md)

Production deployment is **not** M0 acceptance by itself. Acceptance requires the
same-commit OIDC, RLS, backup, security, and compliance evidence described by ADR 0008.

## What runs where

| Component | Source | Notes |
|---|---|---|
| `radiologyos-web-1` | `ghcr.io/jerryboganda/radiologyos-web:<sha>` | joins `platform` + `nginx-proxy-manager_default`, alias `radbrain-web` |
| `radiologyos-api-1` | `ghcr.io/jerryboganda/radiologyos-python:<sha>` | FastAPI/uvicorn, 768m / 1.0 cpu |
| `radiologyos-worker-1` | same python image | Celery, concurrency 1, 512m / 0.5 cpu |
| `radiologyos-migrate-1` | same python image | one-shot `alembic upgrade head` as `radbrain_migrator` |
| `radiologyos-embedder-1` | `ghcr.io/jerryboganda/radiologyos-embedder:<sha>` | voyage-4-nano on CPU (ADR 0019), 3g / 2.0 cpu, project network only, alias `radbrain-embedder`; optional (search degrades to lexical) |
| Postgres / Redis / MinIO | `platform-postgres`, `platform-redis`, `platform-minio` | shared, never started by this project |

## Prerequisites

- Repo `jerryboganda/radiologyos`, branch `main`.
- `production` GitHub environment with secrets `VPS_SSH_KEY`,
  `VPS_KNOWN_HOSTS`, `VPS_SSH_HOST`, and the two RLS DSNs.
- On the host: `/opt/radiologyos/{app.env,secrets.env,platform.yml}` and
  `/opt/platform/projects/radiologyos.env`, all mode 600.

## Normal operation

A push to main runs CI and builds images, but never deploys (ADR 0011). A
deploy happens only after the owner approves it, and is dispatched for one exact
commit on `main`:

```
push to main -> CI + Build images
owner OK     -> gh workflow run deploy-production.yml --ref main -f sha=<40-char sha>
             -> Deploy production -> Verify production RLS + Verify production identity
```

The deploy job refuses unless the SHA is on `main` and both `CI` and
`Build images` have a successful run for it. It checks out and deploys that
exact SHA; the verify workflows check out the revision of the deploy run.

## Verification

```bash
# on the host
cd /opt/radiologyos
docker compose --env-file app.env -f platform.yml ps -a
docker compose --env-file app.env -f platform.yml run --rm -T migrate < /dev/null

# from inside the api container
docker exec radiologyos-api-1 python -c \
  "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/live'); print(r.status, r.read().decode())"
```

Expect `api`, `web` and `worker` healthy, `migrate` exited 0, and no published
ports in the `PORTS` column. The runtime-role RLS proof runs in `Verify production
RLS`, tunnelling `127.0.0.1:15433` to the host's Postgres loopback port. It covers
every `tenant_id` table from the catalog as well as the two-tenant M0 matrix (ADR
0022). `Verify production identity` runs `infra/ops/verify-oidc.py`. That script
checks the login, tokens, forged credentials, role denial, tenant-switch denial and
logout. Collect the same-SHA run table with `python scripts/evidence_record.py <sha>`.

### Readiness, metrics, and the model ledger (ADR 0032)

```bash
# dependency detail: {"checks": {"database": "ok", "redis": "ok", "object_storage": "ok"}}
docker exec radiologyos-api-1 python -c \
  "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
# Prometheus text; loopback/private callers only (404 otherwise, and 404 if METRICS_TOKEN
# is set and the bearer token is missing)
docker exec radiologyos-api-1 python -c \
  "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/metrics').read().decode()[:2000])"
```

`/metrics` shows request counts and latency per route template, rate-limit
refusals, `radbrain_job_steps_total`, and `radbrain_model_calls_total` by agent,
backend, and outcome. Model usage per day and agent, usage-limit pauses, and the
amber "usage window exhausted" alert are on Settings → *Model calls* for admins
(`GET /v1/admin/model-usage`). Every API response carries `X-Request-ID`; the
same id is on audit rows, `llm_calls` rows, and the worker log lines of tasks
the request queued (`task=… tenant=… request=…`).

New optional environment (all have safe defaults):

| Variable | Service | Purpose |
| --- | --- | --- |
| `METRICS_TOKEN` | api | also require `Authorization: Bearer <token>` on `/metrics` |
| `RATE_LIMITS` | api | JSON overrides per bucket, e.g. `{"upload": {"user": {"per_minute": 60, "burst": 200}, "tenant": {"per_minute": 120, "burst": 300}}}` |
| `RATE_LIMIT_ENABLED` | api | `false` switches limits off (incident use only) |
| `MODEL_USAGE_LIMIT_ALERT_PER_HOUR` | api, worker | usage-limit errors per hour before the amber alert (default 5) |
| `KEYCLOAK_ADMIN_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_ADMIN_CLIENT_ID`, `KEYCLOAK_ADMIN_CLIENT_SECRET` | worker | revoke an erased user's sessions (see below) |

### Admin MFA rollout (ADR 0032) — owner present, owner's OK required

Admins (`org_admin`, `superadmin`) must enter an authenticator (TOTP) code at
every sign-in. Nothing changes for other users. Apply it only with the owner
ready to enrol, because their next sign-in stops at "Mobile Authenticator Setup":

1. The owner installs an authenticator app on their phone (Google Authenticator,
   Microsoft Authenticator, Aegis, 1Password, …) and keeps a second factor
   recovery plan: the Keycloak master-realm admin can remove a lost OTP credential.
2. On the VPS as root: `cp infra/ops/keycloak-mfa.sh infra/ops/keycloak_mfa.py
   /opt/radiologyos/keycloak/` and run `/opt/radiologyos/keycloak/keycloak-mfa.sh`.
   It is idempotent. It creates the realm role `mfa_required` (included in both
   admin roles), the TOTP policy, the `radbrain browser` flow, and the
   `radbrain-ops` service client. The client's secret is generated into
   `/opt/radiologyos/keycloak/ops-client.env` (600) and never printed. The
   script ends with a `--check` report (`browserFlow=radbrain browser`).
3. The owner signs out and signs in at `https://radiologyos.polytronx.com`. They
   scan the QR code, enter the 6-digit code, and name the device. Every later
   sign-in asks for a code.
4. Wire session revocation for account erasure into `app.env` (worker), then
   redeploy with the owner's OK:
   `KEYCLOAK_ADMIN_URL=http://radbrain-keycloak-keycloak-1:8080`,
   `KEYCLOAK_ADMIN_CLIENT_ID=radbrain-ops`, and `KEYCLOAK_ADMIN_CLIENT_SECRET`
   from `ops-client.env`.
5. Re-run `Verify production identity`. `verify-oidc.py` signs in as the
   bootstrap user; if that user holds an admin role it now needs a code, so
   either give the verification user the `student` role or update the script.

Roll back by binding the built-in flow again. In the Keycloak admin console,
open *Authentication*, find `browser`, and choose *Bind flow → Browser flow*.
Or run
`kcadm.sh update realms/radbrain -s browserFlow=browser`.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `permission denied for database radiologyos` on `CREATE SCHEMA` | `CREATE SCHEMA` needs database-level `CREATE`, not just schema rights | `GRANT CREATE ON DATABASE radiologyos TO radbrain_migrator` (migrator only) |
| `No such container: radiologyos-api-1` and nothing deployed | `docker compose run` consumed the rest of the script on stdin | keep `-T` and `< /dev/null` on the one-shot `run` |
| Image pull `404 not found` | tag mismatch — `type=sha` publishes `sha-<short>` | build must also publish the bare full SHA; deploy pins it |
| `unbound variable` in a step | step read an env var declared only on other steps | declare workflow-level `env` |
| `Host key verification failed` | multi-line known_hosts secret with CRLF endings | write it with LF, no BOM, and assert with `ssh-keygen -lf` |
| `provision-project.sh` fails on `quay.io/minio/mc` 401 | MinIO privatised its registries after EOL | script now uses the `mc` inside `platform-minio` |

## Rollback

Redeploy the previous image tag; migrations are expand-and-contract, so an
older image tolerates a newer schema.

```bash
cd /opt/radiologyos
sed -i '/^RADBRAIN_PYTHON_IMAGE=/d;/^RADBRAIN_WEB_IMAGE=/d;/^RADBRAIN_EMBEDDER_IMAGE=/d' app.env
printf 'RADBRAIN_PYTHON_IMAGE=%s\nRADBRAIN_WEB_IMAGE=%s\nRADBRAIN_EMBEDDER_IMAGE=%s\n' \
  <python-ref> <web-ref> <embedder-ref> >> app.env
docker compose --env-file app.env -f platform.yml pull
docker compose --env-file app.env -f platform.yml up -d
```

Prefer `gh workflow run deploy-production.yml --ref main -f sha=<previous full sha>`, which does
the same thing through the audited path.

Schema rollback is deliberately absent. Restoring a previous dump would discard
any tenant data written since; take a decision explicitly and prefer a
forward fix.

## Escalation

- Host pressure (swap climbing, load sustained above ~4 on 6 cores): lower the
  caps or move radbrain off this host. Do not raise the caps to fit a leak.
- Platform credential or schema problem: `/opt/platform/bin/provision-project.sh`
  is idempotent and safe to re-run for this project.
- Any suspected cross-tenant read: treat as a security incident. The runtime
  role is `NOBYPASSRLS` and owns no tables, so the RLS proof failing means the
  boundary is genuinely broken, not misconfigured.

## Known limitations

- **Identity is self-hosted Keycloak (ADR 0009)**, deployed as the separate
  `radbrain-keycloak` compose project and configured by the root-run scripts in
  `infra/ops/` (`build-keycloak-env.sh`, `keycloak-bootstrap.sh`,
  `provision-tenant.sh`, `wire-oidc.sh`). Its issuer is public (see **Issuer**
  below); browser sign-in works through `radiologyos.polytronx.com/auth`.
- **Public hostname.** `radiologyos.polytronx.com` is served by the
  nginx-proxy-manager container through a hand-managed file,
  `infra/proxy/radiologyos-manual.conf`, copied to
  `/opt/docker/nginx-proxy-manager/data/nginx/proxy_host/radiologyos-manual.conf`
  (it is not in the NPM database, so NPM's UI does not show or overwrite it).
  `/auth/realms/*` and `/auth/resources/*` go to Keycloak; `/auth/realms/master`
  and the admin console are never routed; everything else goes to `radbrain-web`.
  After editing, run `docker exec nginx-proxy-manager-app-1 nginx -t` before
  `nginx -s reload`. The Let's Encrypt certificate was issued by webroot and is
  renewed by `/etc/cron.d/radiologyos-cert-renew`
  (`infra/proxy/radiologyos-cert-renew.cron`), because NPM only renews
  certificates in its own database.
- **Issuer.** Keycloak pins `KC_HOSTNAME=https://radiologyos.polytronx.com/auth`
  with a dynamic backchannel, so `iss` is
  `https://radiologyos.polytronx.com/auth/realms/radbrain` while JWKS and the
  token exchange stay on `http://radbrain-keycloak-keycloak-1:8080/realms/radbrain`. `app.env` must
  set `OIDC_ISSUER` to the public issuer and `OIDC_JWKS_URL` /
  `OIDC_INTERNAL_ISSUER` to the internal one (`infra/ops/wire-oidc.sh`).
- **Preview is off in production** (`PREVIEW_ENABLED=false` since 2026-09-26, ADR
  0006/0011). `infra/ops/wire-oidc.sh` sets it to `false`; never turn it back on.
- **Backups.** The platform's `bin/backup.sh` dumps databases nightly, on the box
  only. `infra/ops/offsite-backup-gdrive.sh` (host cron) copies the `radiologyos`
  and `keycloak` dumps and mirrors the MinIO bucket to the owner's Google Drive.
  See [backup and restore](backup-restore.md). Off-host dumps are not client-side
  encrypted.
