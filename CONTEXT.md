# CONTEXT.md — radbrain current implementation context

Last reviewed: **2026-09-25**
Milestone: **M0 Foundation — CI/runtime verified; staging workflow ready; staging OIDC exit not yet accepted**
Preview implementation: **M1–M7 may be built locally under ADR 0006; acceptance remains blocked**
Canonical requirements: [`docs/SPEC.md`](docs/SPEC.md)

## Purpose

`radbrain` is a source-controlled implementation of a provenance-first,
tenant-isolated radiology study platform. The intended product supports candidate
material, a knowledge graph, figure bank, exam-driven study plan, grounded tutor,
and assessment engine. The current checkout is only the M0 foundation target; it is
not a usable upload/search product yet.

## Current repository shape

- `apps/api`: FastAPI application, settings, SQLAlchemy session plumbing,
  development-principal API routes, health endpoints, bounded redacted request logging,
  and a local synthetic non-release preview surface for M1–M7 seams.
- `apps/worker`: Celery 5 worker package and stable job identity; durable ingestion is
  not yet established.
- `apps/web`: web scaffold plus a server-proxied `/preview` workspace for synthetic
  non-release flows; no provider tokens are sent to the browser.
- `apps/api/migrations`: Alembic migration target for PostgreSQL, pgvector, and
  tenant RLS; verify the landed migration before calling M0 RLS complete.
- `packages`: model-route, prompt, and eval configuration scaffolds. Model routes
  must remain mock-only until the provider decision gate is approved.
- `evals`: evaluation scaffolding, not a passed quality gate.
- `infra`: Compose and deployment scaffolding; the default stack now contains a
  one-shot migrator, real FastAPI/Celery processes, and the web shell, but this is not
  evidence of a production environment.
- `scripts`: repository maintenance utilities such as OpenAPI type generation.
- `docs`: product index, runbooks, and decision records.

Directories named in the target architecture can exist before their behavior. Use
tests and staging evidence, not directory presence, to determine maturity.

## Commands currently defined

| Command | Purpose |
| --- | --- |
| `make up` | Start the Compose stack and show service status. |
| `make down` | Stop containers while retaining named volumes. |
| `make migrate` | Apply Alembic migrations to the configured database. |
| `make check` | Run lightweight local lint, type, Python test, and web checks. |
| `make test` | Run Python unit tests. |
| `make rls` | Dispatch the protected runtime-role RLS workflow through GitHub Actions. |
| `make types` | Generate TypeScript API types from OpenAPI. |
| `make security-scan` | Dispatch the security scan through GitHub Actions. |
| `make ci` | Dispatch CI for the current revision and wait for its result. |

`make check` is the broad local gate, but success does not substitute for a Compose
integration test, OIDC browser login, a real two-tenant database test, or CI.

## Current API behavior and boundaries

- Public liveness/readiness routes are `/health/live` and `/health/ready`.
- Local routes accept `x-user-id`, `x-tenant-id`, and optional `x-role` headers only
  when `APP_ENV` is `dev`, `development`, or `test`. This is not OIDC and must never
  be enabled in staging, production, or unknown environments.
- The web scaffold implements an OIDC authorization-code/PKCE session shell, but
  full Keycloak browser login is an M0 exit condition only after the API resolves
  the authenticated subject to a current, authorized tenant membership and role.
- Tenant context is a Python `ContextVar`; authenticated OIDC requests resolve the
  current active membership from the database before a tenant-scoped session is opened.
  `tenant_session()` sets transaction-local `app.tenant_id` immediately before tenant
  data access. Development headers set the same context only in the explicit local test
  environments. Endpoint coverage and adversarial two-tenant evidence must still be
  checked separately.
- Export/delete/admin routes in the scaffold are response-shape demonstrations, not
  proof of the M6 deletion workflows.

## Configuration baseline

`.env.example` documents the current settings contract. It includes separate app
and migrator database URLs, OIDC, Redis, S3, embedding dimensions, model config
path, ungrounded-answer guard, and the reserved Core tenant UUID. Values marked
`change-me` and public RustFS defaults are local-development placeholders only.

`ALLOW_UNGROUNDED_DEFAULT=false` is a hard default. Concrete provider models and
provider keys are not approved by `.env.example` or `packages/models/models.yaml`.
Do not place keys in browser-visible configuration.

## M0 definition of done

M0 is complete only when all of the following have evidence on staging:

- `make up` brings up the required stack and health checks pass.
- A real user signs in through OIDC, receives the correct tenant/role membership,
  and cannot select a tenant they do not belong to.
- A two-tenant suite, run as the RLS-bound application role, proves zero
  cross-tenant reads or writes and fail-closed behavior without tenant context.
- OpenAPI-to-TypeScript generation is reproducible and CI checks are green.
- The observability skeleton reports service health without leaking source text,
  prompts, embeddings, credentials, or patient data.
- The runbook, five-minute clean-tenant demo, and security scan are current.

The authoritative checklist and rollback steps are in
[`docs/runbooks/m0-foundation.md`](docs/runbooks/m0-foundation.md). The full remaining
A–Z goal is tracked in [`docs/remaining-work.md`](docs/remaining-work.md).

## Known limitations and open decisions

- Local study directories are Git-ignored private inputs; documentation agents do
  not inspect their contents. Follow the data-handling runbook for any authorized
  local test.
- The model provider, embedding provider, launch data region, and monthly spend cap
  are unapproved. The model ADR is a gate, not a selection.
- The protected M0 staging workflow is implemented but cannot be accepted until the
  `staging` GitHub Environment has required reviewers, variables, and protected secrets.
- CI run `36143277301` on revision `5ac9eff` is green, including full runtime Compose
  startup, live migrations, and the non-privileged two-tenant RLS proof. The checkout
  also contains protected OIDC and staging-RLS workflow definitions plus a local
  synthetic preview; protected staging OIDC/browser acceptance, staging RLS, trace
  review, and release/security approvals remain outstanding.
- Curriculum validation/weights, Core Library sourcing, pricing, retention changes,
  and launch cohort details require human decisions.
