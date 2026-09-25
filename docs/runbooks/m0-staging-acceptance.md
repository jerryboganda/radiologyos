# M0 staging acceptance and RLS runbook

Status: **Workflows implemented; protected staging execution pending**
Scope: M0 slices A–D only; staging OIDC, runtime-role RLS, redacted evidence, and approvals
Related: [`M0 foundation`](m0-foundation.md), [`data handling`](data-handling.md), [RLS ADR](../decisions/0001-tenant-isolation-rls.md), [compute policy](../decisions/0005-github-actions-compute-policy.md)

## Prerequisites

- A clean, reviewed `main` candidate with a green `ci.yml` run for the exact 40-character SHA.
- A protected GitHub `staging` Environment with required reviewers.
- An HTTPS staging deployment of that exact candidate.
- Synthetic OIDC users, memberships, tenant records, and short-lived test tokens.
- Disposable staging tenants and a staging PostgreSQL runtime/migrator role split.
- Synthetic protected database URLs for the RLS proof; never use production credentials.
- No private study files, patient data, DICOM, source text, or real credentials.

The agent cannot create required human reviewer identities, approve a release, or mint
provider/tenant secrets. Those are external prerequisites and must not be replaced by
local substitutes.

## A: provision the environment

Create the protected `staging` Environment and require reviewers before dispatch. Add
these non-secret repository variables:

| Name | Purpose |
| --- | --- |
| `RADBRAIN_STAGING_WEB_URL` | HTTPS web origin |
| `RADBRAIN_STAGING_API_URL` | HTTPS API origin |
| `RADBRAIN_STAGING_DEPLOYED_REVISION` | Exact deployed 40-character SHA |
| `RADBRAIN_STAGING_EXPECTED_TENANT_ID` | Synthetic authorized tenant UUID |
| `RADBRAIN_STAGING_EXPECTED_ROLE` | Expected synthetic role |
| `RADBRAIN_STAGING_EXPECTED_SUBJECT` | Synthetic OIDC subject UUID |
| `RADBRAIN_STAGING_EXPECTED_USER_LABEL` | Synthetic display label |
| `RADBRAIN_STAGING_API_AUDIENCE` | Reviewed API audience |
| `RADBRAIN_STAGING_UNAUTHORIZED_TENANT_ID` | Synthetic unauthorized tenant UUID |

Add these protected secrets; values are never displayed, logged, or committed:

| Name | Purpose |
| --- | --- |
| `RADBRAIN_STAGING_TEST_USERNAME` | Synthetic OIDC test username |
| `RADBRAIN_STAGING_TEST_PASSWORD` | Synthetic OIDC test password |
| `RADBRAIN_STAGING_STUDENT_TOKEN` | Short-lived synthetic student token |
| `RADBRAIN_STAGING_ADMIN_TOKEN` | Short-lived synthetic org-admin token |
| `RADBRAIN_STAGING_EXPIRED_TOKEN` | Short-lived synthetic expired token |
| `RADBRAIN_STAGING_WRONG_AUDIENCE_TOKEN` | Short-lived wrong-audience token |
| `RADBRAIN_STAGING_RLS_ADMIN_DATABASE_URL` | Disposable staging fixture-admin URL |
| `RADBRAIN_STAGING_RLS_RUNTIME_DATABASE_URL` | Non-privileged staging runtime URL |

The RLS admin URL is limited to the protected workflow and disposable fixtures. The
proof must fail if either database URL is absent; an unset secret must never become a
passing skipped test.

## B: OIDC and authorization acceptance

Dispatch [`m0-staging-acceptance.yml`](../../.github/workflows/m0-staging-acceptance.yml)
from `main` with the exact candidate SHA, redacted deployment ID, and references to
the pre-dispatch security, release, and trace reviews. The workflow checks the
candidate SHA, exact CI conclusion, deployed revision, HTTPS origins, and required
environment configuration before running Playwright.

The browser proof covers:

- authorization-code callback and membership-derived tenant/role;
- final URL and callback request without access tokens, ID tokens, or client secrets;
- unauthorized tenant switch denial and unchanged active tenant;
- student denial and org-admin allowance;
- malformed, expired, and wrong-audience token rejection;
- logout and cleared browser session.

Playwright screenshots, video, and traces remain disabled. The workflow uploads no
artifacts. A green run is technical evidence, not human approval.

## C: runtime-role RLS acceptance

Dispatch [`m0-staging-rls.yml`](../../.github/workflows/m0-staging-rls.yml) from
`main`, or set the five non-secret reference variables used by `make rls` and run
`make rls`. The workflow requires the exact deployed SHA, green CI, protected
environment approval, and both protected database URLs. It runs
`evals/checks/test_rls_live.py` as the non-privileged runtime role.

The live proof covers every current M0 tenant table: `tenants`, `users`,
`memberships`, `sources`, `jobs`, `job_steps`, and `audit_log`. It checks:

- runtime role attributes, migrator non-membership, and table ownership;
- no-context reads before and after a reused connection;
- tenant A and B visibility, including the narrow Core read exception;
- cross-tenant update/delete attempts;
- cross-tenant insert attempts and audit-log privilege denial;
- invalid transaction context fail-closed behavior;
- cleanup of synthetic fixtures.

The test must run against the application role, not a superuser, owner, or
`BYPASSRLS` connection. A CI RLS run is not staging evidence.

## D: evidence and approval

Record only redacted references: candidate SHA, deployment ID, migration revision,
role-name/attribute result, test names, OIDC outcomes, RLS result, CI run, generated
contract result, security scan, observability redaction, rollback result, and known
limitations. Do not record environment files, database URLs, tokens, source content,
private paths, or screenshots containing sensitive data.

Obtain the designated engineering, security/privacy, platform, and release approvals.
The pre-dispatch references authorize the test run; the post-run review approves the
result. M0 remains in progress until the checklist is complete.

## Normal operation

1. Confirm the candidate and deployment SHA.
2. Run the protected OIDC workflow.
3. Run the protected RLS workflow.
4. Inspect redacted traces and CI/security results.
5. Complete the M0 evidence record and approvals.

## Common failures

| Symptom | Safe response |
| --- | --- |
| Environment or variable missing | Stop; provision the protected value and rerun Actions |
| Wrong audience | Fix the provider audience mapper and API configuration; never disable validation |
| Runtime RLS secret missing | Treat as a failed staging gate, not a skipped test |
| Superuser/owner detected | Invalidate the result and rerun with the runtime role |
| Cross-tenant row visible | Stop, preserve redacted evidence, and escalate to security |
| Browser artifact requested | Keep artifacts disabled; record redacted references instead |
| Sensitive log/trace found | Stop export, rotate exposed credentials, and follow incident handling |

## Rollback and escalation

Rollback means stopping the staging deployment/workflow, preserving redacted evidence,
and restoring the last reviewed application image. Never disable RLS, use a superuser
as a hotfix, reuse a real credential, or send private content to an unapproved route.
Escalate auth/RLS issues to security, deployment issues to platform, and failed exit
evidence to the release owner.

## Known limitations

This runbook covers M0 only. Upload, parsing, search, tutor, billing, export/delete,
backup, and local-model capabilities remain unimplemented or gated by later slices.
See [`remaining-work.md`](../remaining-work.md) for the A–Z dependency queue.
