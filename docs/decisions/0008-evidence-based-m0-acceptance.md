# 0008 — Evidence-based M0 acceptance without a human reviewer gate

- Status: accepted; amended by [ADR 0022](0022-derived-schema-evidence-and-branch-protection.md)
- Date: 2026-09-25
- Amends: ADR 0005 (compute policy), `AGENTS.md` staging paragraph
- Related: ADR 0001 (tenant isolation), ADR 0007 (production on the shared platform)

## Context

ADR 0005 made the protected `staging` GitHub Environment the only environment
authorised to run M0 staging acceptance, with required reviewers, and the
remaining-work plan required a separate staging deployment target. Two facts
made that design unworkable as written:

1. The repository is public. GitHub does not offer environment *required
   reviewers* for public repositories on free plans, so the gate could never be
   satisfied without either making the repository private or paying for a plan.
2. A separate staging host was never provisioned, so the acceptance target did
   not exist.

The owner reviewed both and directed that the reviewer-gate requirement and the
separate staging-target requirement be removed from the M0 plan.

## Decision

M0 acceptance is **evidence-based and automated**. There is no human
sign-off step and no separate staging environment.

Acceptance is satisfied when all of the following pass on the deployed
production revision, each as a required check on `main`:

| Evidence | Mechanism | Gate |
| --- | --- | --- |
| Tenant isolation under the runtime role | two-tenant plus no-context negative test, connecting as the non-superuser application role over a tunnel to the live database | `Verify production RLS` |
| Migration state | Live and restored alembic head equal the deployed revision's head; every `tenant_id` table has ENABLE + FORCE RLS (derived, ADR 0022; originally head `20260925_0003`, 8 tables, 7 with RLS) | `backup-restore-drill.sh`, `Verify production RLS` |
| Role separation | runtime role is `NOBYPASSRLS`, owns no table, cannot `CREATE`, cannot reach another database | RLS proof assertions |
| Static and dependency security | Ruff, mypy, Bandit, pip-audit, npm audit | `CI` |
| Contract integrity | generated OpenAPI committed and validated | `CI` |
| Deployment correctness | health and readiness from inside the platform network, no published ports | `Deploy production` |
| Backup recoverability | restore into a scratch database, RLS and extensions verified, live database untouched | `backup-restore-drill.sh` |
| Resource discipline | every service capped with `cpus` and `mem_limit`; zero compliance violations | `check-compliance.sh` |

M0 is accepted when these are green for the same commit SHA. Security review is
carried by the automated scans above rather than by a person.

## Consequences

- The M0 acceptance gate is reproducible and cannot be forgotten, because it is
  wired into the same push-driven chain as the deployment. A regression fails
  the merge, not a quarterly review.
- **The residual risk is explicit: no human ever signs off on security,
  privacy, legal, or clinical appropriateness.** Automation cannot judge whether
  a retention period is lawful, whether a claim is clinically correct, or
  whether a dependency advisory is acceptable in context. Those judgements are
  now absent from the process rather than pending in it, and that is a real
  reduction in assurance.
- Every milestone that previously ended in a human approval step is now ended by
  its automated gate. Slices requiring a *substantive* decision rather than a
  sign-off — provider choice, retention, curriculum, pricing — remain blocked
  until the owner makes them, and are recorded as such in
  [`remaining-work.md`](../remaining-work.md).
- The public repository remains public. If it is ever made private, required
  reviewers become available and this ADR should be revisited.

## Rejected alternatives

- **Make the repository private and keep the gate.** Rejected by the owner in
  preference for a public repository.
- **Buy a plan for reviewer support.** Rejected on cost.
- **Keep the gate and accept it is permanently unmet.** Rejected: an
  unsatisfiable gate is worse than an honest automated one, because it reads as
  satisfied in documentation while enforcing nothing.
