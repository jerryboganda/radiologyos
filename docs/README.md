# radbrain documentation

This directory is the documentation entry point for the M0 scaffold and the later
milestones defined by the implementation specification.

## Start here

| Need | Document |
| --- | --- |
| Product, architecture, and milestone source of truth | [`SPEC.md`](SPEC.md) |
| Current implementation snapshot | [`../CONTEXT.md`](../CONTEXT.md) |
| Agent and contributor rules | [`../AGENTS.md`](../AGENTS.md), [`../CLAUDE.md`](../CLAUDE.md) |
| Local and private data rules | [`runbooks/data-handling.md`](runbooks/data-handling.md) |
| M0 operation, verification, rollback, and demo | [`runbooks/m0-foundation.md`](runbooks/m0-foundation.md) |
| Tenant isolation and RLS decision | [`decisions/0001-tenant-isolation-rls.md`](decisions/0001-tenant-isolation-rls.md) |
| Local S3 runtime decision | [`decisions/0003-rustfs-local-s3-runtime.md`](decisions/0003-rustfs-local-s3-runtime.md) |
| Model-provider approval gate | [`decisions/0002-model-provider-gate.md`](decisions/0002-model-provider-gate.md) |
| OIDC API audience decision | [`decisions/0004-api-oidc-audience.md`](decisions/0004-api-oidc-audience.md) |
| GitHub Actions compute policy | [`decisions/0005-github-actions-compute-policy.md`](decisions/0005-github-actions-compute-policy.md) |
| Non-release preview boundary | [`decisions/0006-non-release-preview-mode.md`](decisions/0006-non-release-preview-mode.md) |
| Protected M0 staging and RLS acceptance | [`runbooks/m0-staging-acceptance.md`](runbooks/m0-staging-acceptance.md) |
| Local M1–M7 preview operation | [`runbooks/m1-preview.md`](runbooks/m1-preview.md) |
| M6 preview operations boundaries | [`runbooks/m6-preview-operations.md`](runbooks/m6-preview-operations.md) |
| Remaining-work goal and A–Z queue | [`remaining-work.md`](remaining-work.md) |

## Documentation rules

- State whether a capability is implemented, targeted, or only a requirement.
- Never put source text, prompts containing source text, credentials, patient data,
  tenant data, or private study-file names in documentation.
- Use synthetic identifiers in commands and examples.
- Record material architectural or policy choices as an ADR under `decisions/`.
- Keep operational instructions under `runbooks/` and update them with behavior.
- Prefer links to the canonical implementation over copying large sections of it.

## Current status

- The repository is an M0 foundation scaffold with a local synthetic M1–M7 preview.
  Do not infer M0 or any later acceptance from the preview or this documentation.
  The authoritative exit tests are in the M0 runbooks and require fresh staging
  evidence.
- Compute-intensive checks are dispatched with `make ci` or the protected staging
  workflow; local results are not staging evidence.
