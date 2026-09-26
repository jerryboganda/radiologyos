# ADR 0005: Run compute-intensive verification in GitHub Actions

Status: **Accepted as a repository-wide execution policy**
Date: 2026-09-25
Decision owners: engineering, security, and release reviewers
Scope: CI, integration, browser, database, build, scan, eval, and performance verification

ADR 0008 supersedes this ADR's former M0 staging-environment and human-review gate.
The repository-wide GitHub Actions compute policy remains active.

## Context

The repository has multiple verification classes with different privacy and resource
requirements. Local development is useful for fast feedback, but Docker Compose,
PostgreSQL migrations/RLS proofs, browser acceptance, production builds, dependency and
security scans, evals, and load checks are compute-intensive and can produce sensitive
runtime data. A local pass can also be mistaken for staging evidence. The repository
already has a GitHub Actions CI workflow, but it lacked an explicit project-wide compute
policy and a protected staging acceptance entry point.

## Decision

All compute-intensive verification MUST run in GitHub Actions. Local execution is
limited to lightweight syntax, unit, lint, type, and diff checks, and those results are
never substitutes for a missing or failed Actions result. M0 browser/OIDC and
runtime-role RLS acceptance run only through the manual `m0-staging-acceptance.yml` and
`m0-staging-rls.yml` workflows on `main`, using the protected `staging` GitHub
Environment and exact candidate revisions.

> Superseded in part: ADR 0008 removed the staging workflows (now deleted) and moved
> M0 OIDC and RLS evidence to `verify-production-oidc.yml` and
> `verify-production-rls.yml`. The staging paragraphs below are kept as history.

The staging workflows use protected environment variables/secrets, keep Playwright
screenshots/video/traces disabled, upload no artifacts, and record only redacted
operational references. They execute only the trusted `main` workflow SHA, require that
SHA to have green CI, and require the protected deployed-revision variable to match.
The protected environment must have human reviewer rules; a workflow success is not a
security or release approval. The RLS workflow fails closed when its disposable database
URLs are absent rather than treating a skipped proof as a pass.

## Consequences

- Contributors get fast local feedback without accidentally treating it as deployment
  evidence.
- CI becomes the authoritative location for builds, integration tests, browser tests,
  scans, migrations, RLS proofs, evals, and performance checks.
- Staging operators must configure a protected environment, required reviewers, short-lived
  synthetic test credentials/tokens, and redacted approval/trace references.
- Missing staging configuration fails closed; it does not trigger a bypass or a claim of
  M0 acceptance.
- Workflow logs and artifacts must remain free of credentials, tokens, private paths,
  source text, patient data, and tenant content.

## Rejected alternatives

- **Run heavy checks locally when convenient:** inconsistent resource use and a high risk
  of presenting local results as staging evidence.
- **Automatically promote a green CI run to staging acceptance:** CI cannot prove a real
  browser flow, production-like configuration, or human security/release approval.
- **Upload browser artifacts for convenience:** screenshots, traces, and videos can
  contain tokens, personal data, or private application content.

## Verification

The repository static check verifies that the staging workflows are manual,
environment-bound, secret-safe, artifact-free, and use the required browser/database
targets. The exact candidate must also have a green CI run and green M0 staging OIDC
and RLS runs before the M0 checklist can be completed.
