# AGENTS.md — radbrain repository guidance

## Read and preserve

1. Read [`docs/SPEC.md`](docs/SPEC.md), this file, [`CONTEXT.md`](CONTEXT.md),
   [`CLAUDE.md`](CLAUDE.md), and the relevant runbook/ADR before changing files.
2. Work one milestone at a time in M0-to-M7 order. Do not claim a later capability
   merely because a directory, placeholder, or interface exists.
3. Make targeted edits. Preserve public behavior unless an approved change requires
   it. Do not rewrite a file to change one function.
4. Work only in the paths assigned by the active task. Documentation changes belong
   under `docs/` or the named root guidance files; application code is not a docs
   worker's responsibility.

## Non-release preview exception

ADR 0006 permits M1–M7 implementation in an explicitly local/test-only preview mode
using synthetic or mock/local data. This is an implementation-sequencing exception,
not a staging or release acceptance exception: M0–M7 exit gates, human approvals,
tenant isolation, provenance, privacy, and provider decisions remain unchanged. Preview
artifacts must be labelled non-release and must never be presented as staging evidence.

## Product and safety boundaries

- The application is a study aid, not a medical device.
- Do not inspect, copy, summarize, hash, index, commit, or upload the contents of
  `Radiology Exam Material/` or `Radiology Images/` without an explicit user
  instruction that authorizes the specific local test.
- Never add real credentials, provider keys, personal data, patient data, tenant
  data, source text, or private study-file names to code, tests, fixtures, logs,
  issues, screenshots, or docs. Use synthetic data and reserved example UUIDs.
- Reject DICOM in v1. Identifiable patient data must not be used for development or
  evaluation.
- Do not promote content derived from a user upload to the Core Library.
- Do not select or replace a model/embedding provider, curriculum weights, exam
  blueprint, price, plan limit, copyright position, or retention period without an
  explicit human decision and ADR.
- Stop on ambiguity that can change privacy, isolation, legal, clinical, billing,
  or provider commitments.

## Architecture invariants

- Use Python 3.12/FastAPI/Pydantic v2/async SQLAlchemy/Alembic in `apps/api`.
- Use Celery 5 on Redis in `apps/worker`; long jobs are idempotent and resumable.
- Use SvelteKit 2/TypeScript/Tailwind in `apps/web`; generate client contracts from
  OpenAPI rather than hand-maintaining divergent types.
- Use PostgreSQL 16 with pgvector, tsvector, and RLS; Redis; and private
  S3-compatible object storage.
- Call models only through the configured named routes. Route names are stable API;
  concrete providers and model names are configuration, never inline code.
- Do not add LangChain, LlamaIndex, Haystack, Obsidian, or a Second Brain OS fork.
- Keep explicit retrieval stages and version prompts, schemas, and pipeline outputs.

## Tenant and authorization rules

- Every tenant-scoped table must carry `tenant_id`, enable RLS, and include a
  two-tenant negative test against the application database role.
- Derive tenant context from authenticated membership. Never trust a body/query
  tenant ID by itself.
- Set `app.tenant_id` transaction-locally before tenant queries and fail closed
  when context is absent. Reset context when requests or jobs end.
- The application role must not own protected tables and must not have `BYPASSRLS`.
  Migrations use a separate role.
- Authorize privileged roles in a shared dependency/service layer and audit
  mutations. Admin UI visibility is not authorization.
- Prefix tenant object keys and cache keys with the tenant UUID. Only explicit,
  reviewed Core content may use shared scope.
- Never use header-based development identity outside local development.

## Repository-wide compute policy

All compute-intensive verification MUST run in GitHub Actions. This includes Docker
Compose startup, browser/E2E tests, integration tests, database migrations, RLS proofs,
production builds, security/dependency scans, evals, and performance/load checks. Local
runs are limited to lightweight syntax, unit, lint, type, and diff checks. A local pass
must never be reported as a substitute for a missing or failed Actions result.

The protected `staging` GitHub Environment is the only environment authorized to execute
M0 staging acceptance. Its configuration, required reviewers, and secret names are
operational prerequisites; secrets and credentials must never be committed or printed.
The test-only `@playwright/test` dependency is pinned in the web lockfile for the manual
GitHub Actions browser acceptance workflow; it is not shipped in the web runtime.

## Change workflow

1. State the plan and affected paths.
2. Gather relevant code, spec, conventions, and tests before editing.
3. Add or update tests for security and core behavior before implementation.
4. Keep migrations expand-and-contract and preserve zero-downtime compatibility.
5. Run the narrow check first, then the repository checks that exist and are
   relevant. Record unavailable checks and environmental limitations explicitly.
6. Update the relevant runbook and ADR for operational or architectural changes.
7. Inspect the final diff and repository status; verify no out-of-scope or private
   files changed.

Use Conventional Commits and one feature per pull request. A proposed loop is:

```text
plan -> tests -> implementation -> lightweight local checks -> make ci
     -> make types -> review runbook/ADR -> inspect diff
```

Run integration or eval targets only when they exist in the checkout. Never report
a target as passing when it was skipped or is not defined.

## Documentation standards

- Every document states status and scope.
- Separate requirements, current implementation, and future plans.
- Use accessible relative Markdown links and synthetic examples.
- Runbooks include prerequisites, normal operation, verification, common failures,
  rollback, escalation, and known limitations.
- ADRs include context, decision, consequences, rejected alternatives, and status.
- Keep documentation under 400 lines and link canonical detail instead of
  duplicating sensitive or volatile content.
