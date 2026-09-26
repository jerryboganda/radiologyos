# M0 Foundation runbook and five-minute demo

Status: **CI/runtime verified; production verification extended (ADR 0022); M0 evidence record pending in [`docs/evidence/m0.md`](../evidence/m0.md)**
Scope: local development scaffold and production evidence acceptance for M0 only
Related: [`data handling`](data-handling.md), [RLS ADR](../decisions/0001-tenant-isolation-rls.md), [model gate](../decisions/0002-model-provider-gate.md)

## 1. Purpose and exit contract

M0 establishes the monorepo, Compose development stack, PostgreSQL with pgvector,
tenant RLS, OIDC login and membership, generated TypeScript API contracts, CI,
observability skeleton, and health endpoints.

M0 is complete only when all four specification conditions have fresh evidence for
the same production candidate commit:

1. `make up` brings up the required stack.
2. A real user logs in through OIDC and receives only an authorized tenant/role.
3. The two-tenant RLS suite passes as the non-privileged application role.
4. CI is green.

CI run `36143277301` for revision `5ac9eff` is green. It verifies Python, web,
OpenAPI reproducibility, security scans, Compose validation, live migrations, the
non-privileged two-tenant RLS proof, and the full runtime Compose startup/API-web-
worker health path. This is strong CI/runtime evidence, but it is not production
OIDC/RLS acceptance evidence; keep the checklist unchecked until the production
verification chain records all required results for one candidate. There is no
staging environment: acceptance runs on the deployed production revision (ADR 0008,
amended by ADR 0022), and the result is written to `docs/evidence/m0.md`.

## 2. Architecture and service map

The target Compose service names are:

| Service | M0 purpose | Expected local address/protocol |
| --- | --- | --- |
| `web` | SvelteKit PWA shell and auth UI | `http://localhost:3000` |
| `migrate` | One-shot Alembic migration using the migrator role | no browser endpoint |
| `api` | FastAPI health/OpenAPI entry point | `http://localhost:8000`; docs at `/docs` |
| `worker` | Celery worker process | no browser endpoint |
| `postgres` | PostgreSQL 16 + pgvector, migrations/RLS | database only; host port per Compose |
| `redis` | Queue, cache, and rate-limit service | `redis://localhost:6379` by default |
| `storage` | Private S3-compatible storage (RustFS) | API `http://localhost:9000`; console `:9001` |
| `keycloak` | OIDC identity provider | `http://localhost:8080`; realm `/realms/radbrain` |

Verify actual published ports with `docker compose config` and `docker compose ps`;
this table is not a substitute for the checked-in Compose file. The default stack starts
PostgreSQL, Redis, RustFS, Keycloak, a one-shot migration job, the real FastAPI API,
the real Celery worker, and the web shell. The migration job completes before the API
and worker start. CI and a local Docker installation are required to execute this
startup sequence successfully; Compose configuration validation alone is not an exit
test.

## 3. Prerequisites

- Windows PowerShell (commands below are PowerShell-compatible).
- Git and a clean, reviewed worktree.
- Python 3.12+ with the project dev dependencies available.
- Node.js 24 and npm (the current web package requires Node 24).
- Docker Desktop/Engine with Compose v2 and enough resources for the stack.
- `make` if using the repository convenience targets; individual commands can be run
  directly when documenting a failure.
- Synthetic M0 fixtures and disposable local or CI tenants only.

Never prepare M0 by copying the ignored private study directories into fixtures.
Do not put real credentials or provider keys in `.env`.

## 4. Configuration

Create local configuration from the checked-in template:

```powershell
Copy-Item .env.example .env
```

Review every value even when the local default is convenient:

- `DATABASE_URL` is the RLS-bound runtime role; `DATABASE_MIGRATOR_URL` is separate.
- `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_AUDIENCE` define
  the local realm/client and the API resource-server audience. The checked-in disposable
  local realm maps the API audience into access tokens; align the environment with that
  realm for local use, or rotate the local client and realm consistently. Never reuse a
  local value in production.
- `S3_*` settings describe the private RustFS bucket in development.
- `MODELS_CONFIG_PATH` points to checked-in mock route configuration.
- `ALLOW_UNGROUNDED_DEFAULT` remains `false` while provider approval is open.
- `COOKIE_SECURE=false` is local HTTP only. Production requires HTTPS and
  secure cookies.

The template may contain disposable local credentials. They are not production
secrets and must not be reused, published, or used for a shared environment.

## 5. Start the stack

From the repository root:

```powershell
make up
```

If the Make target is unavailable, run the commands it wraps:

```powershell
docker compose up -d
docker compose ps
```

The default startup sequence is:

1. PostgreSQL initializes the disposable superuser, `radbrain_migrator`, and
   `radbrain_app`.
2. The `migrate` one-shot job applies Alembic with `DATABASE_MIGRATOR_URL`.
3. The real API and Celery worker start with the RLS-bound runtime database URL.
4. The web shell starts after API health and connects to the API's internal URL.

Verify the sequence with `docker compose ps` and the health endpoints below. A
running container list or a successful process start is supporting evidence; M0 still
requires the live OIDC and two-tenant acceptance tests on production.

Once a real migration configuration and database exist, apply migrations as the
migrator role:

```powershell
make migrate
```

Expected M0 result: all required services are real application dependencies, report
healthy/running, migration reaches the checked-in head revision, and API readiness
returns `ready`. Some services may take time on first image pull. A process being
listed—or a placeholder returning HTTP 200—is not a health check.

## 6. Health and contract verification

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
Invoke-RestMethod http://localhost:3000/api/health
```

Open `http://localhost:3000`, `http://localhost:8000/docs`, and
`http://localhost:8080` manually and record the result. Port conflicts, a reverse
proxy, or a configuration change can alter URLs; the checked-in Compose mapping and
the production proxy configuration are authoritative.

Regenerate web contract types with `make types`. Review the generated diff. An empty
command is not evidence that generation succeeded.


## 7. Authentication and authorization verification

### Local development identity (supporting API test only)

Only `APP_ENV=dev`, `development`, or `test` may use development headers. Staging,
production, unknown environments, and malformed values require a verified OIDC
access token.

```powershell
$headers = @{
  'x-user-id'   = '10000000-0000-0000-0000-000000000001'
  'x-tenant-id' = '20000000-0000-0000-0000-000000000002'
  'x-role'      = 'student'
}
Invoke-RestMethod http://localhost:8000/v1/me -Headers $headers
```

This proves local route wiring only. It does not prove OIDC, token validation,
membership lookup, refresh behavior, MFA, audit, or production rejection.

### OIDC acceptance test

1. Open `http://localhost:3000/auth/login` and sign in with a synthetic M0 user.
2. Complete the Keycloak callback at `/auth/callback`; return to the web app
   without token or secret values in the URL.
3. Confirm the session UI/API shows the expected user, authorized tenant, and role,
   but no token value.
4. Attempt to switch to a tenant the user cannot access. It fails closed and the
   active tenant does not change.
5. Exercise a student-denied and org-admin-allowed route. Capture server status
   and audit evidence; UI visibility alone does not count.
6. Repeat with expired, invalid, or audience-mismatched tokens. Access is denied.
7. Log out through `/auth/logout`; the browser session is cleared. Provider-side
   logout is proven by `infra/ops/verify-oidc.py`: a backchannel logout, after which
   the refresh token is refused.

Steps 4–7 are automated in production by `Verify production identity`
(`infra/ops/verify-oidc.py`). Tenant switch to a random tenant must return 403.
Spoofed development headers and forged web assertions must return 401 on admin routes.
Admin routes must follow the membership role. With `--student-file`, a synthetic
student must get 403 on `/v1/admin/embedding-usage`.

OIDC browser login and membership enforcement are implemented in the scaffold, but
remain **unaccepted** until the production verification flow captures the result. The API resolves the
verified subject against current active database memberships. A tenant-scoped
session then sets transaction-local `app.tenant_id` before data access; the web shell
must still pass a real API identity through the complete flow.

## 8. Tenant-isolation acceptance

Run `make rls`; it dispatches the production runtime-role proof documented in the
`verify-production-rls.yml` workflow. The proof reads the table list from
`pg_catalog`, so it covers every `tenant_id` table. Each must have ENABLE + FORCE RLS,
return no rows without a valid context, and refuse foreign-tenant inserts. The
catalog must also match the data-rights registry (ADR 0022). Evidence must show the
test connected as the
non-privileged runtime role, not a PostgreSQL superuser or table owner. Follow
[ADR 0001](../decisions/0001-tenant-isolation-rls.md): two tenants
attempt every applicable read/write path; context is absent on a reused connection;
invalid context fails closed; the Core policy is narrow; privileged roles have no
bypass.

Record the migration revision, runtime role attributes (no password), test names,
and redacted A-to-B/B-to-A read, write, missing-context, and tenant-switch results.
Unit tests of `ContextVar` behavior do not satisfy this gate without database evidence.

## 9. CI and observability acceptance

Run available broad checks and record exact failures rather than substituting a
partial check:

```powershell
make check
make types
make security-scan
```

CI must install locked dependencies, run the web/Python checks, start the required
integration services, apply migrations, and execute the RLS suite. The full runtime
job also builds the real API/worker images, waits for API/web health, and verifies a
Celery worker ping. Mocks may support unit tests but cannot replace Compose/PostgreSQL
integration.

Verify health endpoints, structured redacted logs, request/trace IDs, and the
observability skeleton. A dashboard, queue metric, or collector config is not a pass
unless it reports the expected signals without source text, prompts, embeddings,
credentials, tokens, or signed URLs. The provider-free M0 skeleton must not enable
unapproved telemetry/model egress.

## 10. Common failures

| Symptom | Checks | Safe response |
| --- | --- | --- |
| `make` not found | `Get-Command make` | Run the documented underlying command or install/approve tooling |
| Port already allocated | `docker compose ps`; `Get-NetTCPConnection -LocalPort ...` | Stop the conflicting disposable process or use approved config |
| Image pull/build failure | `docker compose pull` / `build` output | Retry once; inspect registry/network; do not change image ad hoc |
| Service unhealthy | `docker compose ps`; `docker compose logs --tail=100 <service>` | Use redacted logs; fix dependency/config before restart |
| DB connection refused | Postgres health, URL host/port, migration role | Correct local config; never substitute a superuser URL |
| Migration revision mismatch | migration status and schema history | Diagnose forward; do not stamp/reset a shared database |
| RLS tests deny legitimate access | role grants, policy, transaction context | Fix reviewed policy/transaction code; never disable RLS |
| RLS tests pass as owner/superuser | inspect role attributes | Test result is invalid; rerun as runtime role |
| OIDC redirect error | issuer, client ID/secret, redirect URI, realm | Align the synthetic test client; never expose the secret |
| Web/API shows API unavailable | placeholder status and Compose API URL | Start/replace the real API integration; a stopped/placeholder responder is not E2E proof |
| Unauthorized development headers | `APP_ENV`, deployment environment | Disable headers outside local; use real OIDC |
| Generated TS types absent/stale | `make types`, OpenAPI, ignored path | Fix generator/contract and record generated diff |
| Telemetry contains sensitive fields | log/trace configuration and test payload | Disable exporter, rotate secrets if needed, escalate |

Never paste environment dumps, tokens, database URLs with passwords, or source text
into an issue or demo. Redact values while retaining the field name and failure class.


## 11. Stop, rollback, and recovery

### Normal stop

```powershell
make down
```

This preserves named volumes. It is the default for local maintenance.

### Destructive local reset

Only after confirming the stack is disposable and no evidence/backup is needed:

```powershell
docker compose down -v
```

This deletes local database/object volumes. Never use it against shared, staging,
or production data. Private study directories are outside Compose and are not
removed by this command; do not add commands that delete them.

### Application rollback

1. stop writes/jobs and preserve redacted health/audit evidence;
2. roll back application/web configuration to the last known-good image;
3. if migration compatibility permits, leave the expand migration in place;
4. never disable RLS, switch to owner/superuser, accept header identity outside dev,
   or send data to an unapproved provider as a rollback shortcut;
5. for a security incident, revoke credentials/sessions and follow the data-handling
   incident procedure; rollback is not containment by itself;
6. rerun health, OIDC, RLS, and CI gates before reopening traffic.

A contract migration that stops writing to an old column cannot be reverted with a
simple image rollback. Use the expand-and-contract runbook, retain compatibility,
and obtain a reviewed forward/rollback migration. Database restore is a separate,
approved disaster-recovery action; do not improvise it on a shared environment.

## 12. Five-minute demo from a clean tenant

Use the deployed candidate, synthetic users/data, and a redacted screen. A placeholder
or route skeleton may be demonstrated as such, but the final M0 verdict is based on
evidence.

| Time | Action | Expected evidence |
| --- | --- | --- |
| 0:00–0:30 | Show clean tenant/session and current revision | no private content; no tokens in screen/logs |
| 0:30–1:15 | Start/reveal stack; call API live/ready and web health | all required services healthy |
| 1:15–2:15 | Log in through OIDC; show user, tenant, role | callback succeeds; values derived from membership |
| 2:15–3:00 | Attempt unauthorized tenant switch and student admin access | both denied; active context unchanged; audit present |
| 3:00–4:00 | Show `make rls` result and one redacted A↔B negative case | runtime role; zero cross-tenant reads/writes |
| 4:00–4:40 | Show OpenAPI, generated TS types, CI, redacted health/trace | reproducible contract; CI green; no content leak |
| 4:40–5:00 | State M0 verdict and open risks | four exit conditions or explicit remaining gap |

Demo rules:

- Never use patient data or the private study directories.
- Use synthetic A/B tenant users with deliberately different roles.
- Show the OIDC authorize step without exposing code, client secret, access token,
  refresh token, signed URL, or database credential.
- Do not edit a tenant ID into a request and call authorization successful if the
  server returned B's data; the expected result is denial/empty/not found.
- Do not call a development-header response “login works.”
- If a required flow is absent, mark it incomplete rather than improvising a bypass.

## 13. M0 evidence record

The record lives in [`docs/evidence/m0.md`](../evidence/m0.md). The orchestrator writes
it after the deploy. Start from `python scripts/evidence_record.py <sha>`, then add
the drill summary from `infra/ops/backup-restore-drill.sh` and the compliance result.
Attach or link only redacted, non-sensitive evidence:

- revision/image digest and deployment ID;
- date/operator role and Compose profile/config variant (secrets omitted);
- health responses and service status;
- migration head and runtime-role attribute check;
- OIDC success, unauthorized switch, invalid-token, and logout results;
- two-tenant/no-context RLS result;
- CI run, type generation, and security scan;
- observability sample proving redaction;
- known limitations and rollback result.

Do not attach environment files, database dumps, raw tokens, source pages, prompts,
private paths/file listings, or screenshots containing secrets/private content.

## 13.1 GitHub Actions-only compute and production acceptance evidence

All compute-intensive verification is dispatched to GitHub Actions. Production OIDC
and runtime-role RLS procedures run after deployment through
`verify-production-oidc.yml` and `verify-production-rls.yml`. The checks use redacted
evidence and protected production configuration; a workflow success must be paired
with the other same-commit release checks.

## 13.2 Verified CI/runtime evidence
- **Revision:** `5ac9eff` (`5ac9efff27dbc7aafd31cc3bb6de5748a6fc91b5`)
- **Workflow:** CI run `36143277301`
- **Green jobs:** Python checks, Web checks, OpenAPI contract, Security scans, Compose validation, Full runtime Compose, and Migration/RLS validation.
- **Live database proof:** migrations reached head and the current RLS proof passed through the non-privileged application role in CI.
- **Runtime proof:** the real API, Celery worker, PostgreSQL, Redis, RustFS, Keycloak, and web services started in GitHub Actions; API/web health and worker ping passed.
- **Not included:** production OIDC/RLS verification and the remaining same-commit
   release evidence, which must be captured for the candidate under ADR 0008.

## 14. Current limitations and escalation

The M0 runtime and CI evidence is recorded above. Confirm production configuration and
actual ports before the acceptance demo.
The web shell now exchanges the code, verifies the ID token, and calls the API with the
access token so the session stores only API-authorized tenant/role values. A successful
browser redirect alone is not acceptance evidence; run the full flow and record
redacted results.
Escalate to:

- **security owner** for RLS, auth, credential, cross-tenant, or sensitive-log issues;
- **platform owner** for Compose/Postgres/Redis/RustFS/Keycloak availability;
- **application owner** for API/web contract or migration incompatibilities;
- **release owner** for failed exit evidence or rollback.

## 15. M0 completion checklist

- [x] `make up` equivalent full Compose startup and migration to head pass in CI
- [x] liveness/readiness and web health are meaningful, not constant success shells
- [ ] real OIDC login/callback/logout works with membership-derived tenant/role
- [ ] unauthorized switch, invalid token, and role denial are proven in production verification
- [x] CI two-tenant RLS/no-context suite passes as non-privileged runtime role
- [ ] production two-tenant RLS/no-context suite passes as non-privileged runtime role
- [x] OpenAPI-to-TypeScript generation and repository checks pass
- [x] CI is green on the candidate revision (`5ac9eff`, run `36143277301`)
- [x] full runtime Compose startup, API/web health, and worker ping pass in CI
- [x] observability skeleton emits bounded redacted request signals
- [ ] production trace/metric review is recorded
- [ ] production OIDC login/callback/logout works with membership-derived tenant/role
- [ ] no open critical/high security finding
- [ ] runbook and clean-tenant five-minute demo are current and approved
Record the evidence for the same candidate commit. Until then, report **M0 in progress**,
not complete.
