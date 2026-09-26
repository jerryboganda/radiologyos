# radbrain specification index

Status: **deployed to production for the owner's tenant (ADR 0011); no milestone accepted yet — M0 evidence record pending.** Tracking: [`completion-plan.md`](completion-plan.md)
Baseline: [`FCPS Radiology Brain OS — Coding-Agent Implementation Spec.md`](../FCPS%20Radiology%20Brain%20OS%20%E2%80%94%20Coding-Agent%20Implementation%20Spec.md)

## Authority and precedence

The root implementation specification above is the supplied product baseline. This
file is the repository working source of truth referenced by `CLAUDE.md`; it
incorporates that baseline by reference and records repository-specific paths and
current maturity. If wording conflicts, preserve the baseline and raise an ADR
rather than silently rewriting product intent.

Never copy the supplied private study directories or their contents into this file.

## Product definition

`radbrain` is a provenance-first, tenant-isolated radiology study platform for
candidate-owned educational material. It supports personal and multi-tenant
deployment while keeping uploaded books, derived claims, embeddings, and generated
content inside the owning tenant. It is a study aid, not a medical device, PACS, or
DICOM viewer in v1.

## Non-negotiable outcomes

1. Claims and generated study content resolve to source, page, block, and where
   applicable figure bounding-box provenance.
2. PostgreSQL row-level security, not request filters alone, prevents cross-tenant
   reads and writes.
3. Exam date drives plans and reminders once the learning-engine milestone lands.
4. Figures are first-class, retain page provenance, and support original-resolution
   zoom.
5. Source conflicts become explicit `KNOWLEDGE_CONFLICT` decisions.
6. Models are reached through named routes with tenant budgets and local fallback;
   no provider is selected by this documentation.
7. Long operations are resumable, idempotent, and expose step status.
8. Uploaded personal copies are never redistributed; Core Library content is
   company-authored or licensed.

## Architecture baseline

- `apps/api`: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic.
- `apps/worker`: Celery 5 on Redis; idempotency includes pipeline version.
- `apps/web`: SvelteKit 2, TypeScript, Tailwind, PWA; OpenAPI-generated types.
- Data: PostgreSQL 16 with pgvector, tsvector, and RLS; private S3-compatible
  object storage; Redis for queues, caches, and rate limits.
- Models: LiteLLM route names `reason`, `extract`, `classify`, `vision`, and
  `local`; route configuration belongs in `packages/models/models.yaml` in this
  scaffold. Provider selection remains gated by ADR 0002.
- Parsing and model workers are later-milestone components; directories may exist
  before the behavior is implemented.

## Milestone gates

Milestone acceptance proceeds in order. The next milestone starts only after the
current milestone passes its exit evidence and its definition of done. Exit evidence is
automated and gathered on the deployed **production** revision for one commit SHA (ADR
0008, amended by ADR 0022 with derived schema checks). There is no separate staging
environment. Under
ADR 0006, local/test-only implementation of a later slice may proceed in an explicitly
non-release preview mode, but it cannot be claimed accepted or release-ready.

| Milestone | Intended outcome | Exit-test pointer |
| --- | --- | --- |
| M0 Foundation | Compose stack, pgvector, RLS, OIDC, tenancy/roles, generated types, CI, observability skeleton, health | [`runbooks/m0-foundation.md`](runbooks/m0-foundation.md) |
| M1 | Upload, reader, cited search | M0 complete first |
| M2 | Knowledge graph, claims, conflicts, curriculum | M1 complete first |
| M3 | Grounded tutor and retrieval, including the reranker (ADR 0028, ADR 0034) | M2 complete first |
| M4 | Exam-first planner and spaced repetition | M3 complete first |
| M5 | Assessments, grading, and exam mode | M4 complete first |
| M6 | Hardening, export/delete, retention purge, ops (ADR 0032), backup drill. Billing is out of release scope until the owner sets pricing (ADR 0011, ADR 0034) | M5 complete first |
| M7 | Portability: durable Markdown/Obsidian-compatible vault export with round-trip link reading (ADR 0031, ADR 0034). Certified local mode, mobile and institution SSO were removed by ADR 0009 | M6 complete first |

Evidence records live in [`evidence/`](evidence/README.md) and five-minute demos in
`demos/`.

Every milestone requires tests, relevant evals, a runbook, a five-minute demo
from a clean tenant, and no open critical or high security finding.

## Security and data invariants

- All tenant-scoped tables require `tenant_id`, RLS, and a negative two-tenant
  test run as the non-privileged application role.
- The API transaction sets tenant context locally before tenant data access.
  Missing context fails closed.
- Cache keys include `tenant_id` unless the item is explicitly Core scope.
- Object keys include `tenant_id`; buckets are private and URLs are short-lived.
- DICOM and identifiable patient data are rejected in v1.
- Identifiers detected in content cause quarantine, not silent publication.
- Logs contain IDs and hashes, not source text, prompts, embeddings, or secrets.
- Personal data is minimized; export and deletion include derived data, caches,
  embeddings, and object files under the approved retention policy.

See [`runbooks/data-handling.md`](runbooks/data-handling.md),
[`decisions/0001-tenant-isolation-rls.md`](decisions/0001-tenant-isolation-rls.md),
[`decisions/0002-model-provider-gate.md`](decisions/0002-model-provider-gate.md),
[`decisions/0004-api-oidc-audience.md`](decisions/0004-api-oidc-audience.md), and
[`decisions/0005-github-actions-compute-policy.md`](decisions/0005-github-actions-compute-policy.md).

## Repository decisions and open questions

Accepted implementation rules live in `docs/decisions/`. ADR 0006 permits only
explicitly non-release local/test preview implementation; it does not change the
milestone acceptance gates. Open questions are not implementation permission. In
particular, curriculum weights, exam blueprints, pricing, retention changes,
patient-data handling, and model/embedding provider selection require explicit human
approval. See `CLAUDE.md` for the stop gates.
