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
| Production on the shared platform VPS | [`decisions/0007-production-on-shared-platform.md`](decisions/0007-production-on-shared-platform.md) |
| Evidence-based M0 acceptance | [`decisions/0008-evidence-based-m0-acceptance.md`](decisions/0008-evidence-based-m0-acceptance.md) |
| Identity, billing, and retention decisions | [`decisions/0009-identity-model-billing-retention.md`](decisions/0009-identity-model-billing-retention.md) |
| Models via Claude Opus 5.5 subscription; Voyage embeddings | [`decisions/0010-claude-subscription-model-routes.md`](decisions/0010-claude-subscription-model-routes.md) |
| Personal-first delivery, manual deploys, parked billing | [`decisions/0011-personal-first-delivery.md`](decisions/0011-personal-first-delivery.md) |
| M0 production evidence and RLS acceptance | [`runbooks/m0-foundation.md`](runbooks/m0-foundation.md) |
| Production deploy, rollback, and known gaps | [`runbooks/production-deploy.md`](runbooks/production-deploy.md) |
| Local M1–M7 preview operation | [`runbooks/m1-preview.md`](runbooks/m1-preview.md) |
| M2 knowledge and editor authority | [`runbooks/m2-preview.md`](runbooks/m2-preview.md) |
| M3 retrieval, grounding, tutor threads | [`runbooks/m3-preview.md`](runbooks/m3-preview.md) |
| Grounded tutor: figures, grounding judge, SSE streaming | [`runbooks/tutor.md`](runbooks/tutor.md) |
| M4 planner, Today, scheduling | [`runbooks/m4-preview.md`](runbooks/m4-preview.md) |
| M5 items, exam mode, autosave | [`runbooks/m5-preview.md`](runbooks/m5-preview.md) |
| M6 preview operations boundaries | [`runbooks/m6-preview-operations.md`](runbooks/m6-preview-operations.md) |
| M7 local mode and portable export | [`runbooks/m7-preview.md`](runbooks/m7-preview.md) |
| Backup, restore drill, RPO/RTO | [`runbooks/backup-restore.md`](runbooks/backup-restore.md) |
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

- radbrain is deployed in production on the shared platform VPS. It starts no
  backing service of its own: Postgres, Redis and MinIO come from the shared
  `platform` project. See [`runbooks/production-deploy.md`](runbooks/production-deploy.md).
- Production deployment is **not** acceptance by itself. M0–M7 exit evidence must
  pass for the same commit through the required verification workflows.
- The non-release preview surface is enabled in production behind OIDC
  authentication (ADR 0009). Do not infer M0 or any later acceptance from the
  preview, from the deployment, or from this documentation.
- Production deploys are manual and need the owner's explicit OK (ADR 0011).
- Compute-intensive checks are dispatched with `make ci` and the production
  verification workflows; local results are not release evidence.
