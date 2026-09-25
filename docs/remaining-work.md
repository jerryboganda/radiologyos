# Remaining-work goal: M0 acceptance through M7

Status: **Active goal — M0 staging acceptance blocked; local M1–M7 preview available**
Scope: all remaining product slices A–Z, in strict milestone order
Owner: autonomous engineering execution, with human approval gates preserved
Last reviewed: **2026-09-25**

## Objective

Complete the radiology study platform from the current M0 foundation through M7,
while preserving tenant isolation, provenance, privacy, clinical-safety, legal,
provider, billing, and operational approval boundaries. No later milestone may be
claimed complete before the preceding milestone passes its staging exit test.

## Non-negotiable execution rules

- Milestone acceptance remains M0 → M7. Under ADR 0006, local/test-only M1–M7 preview
  implementation may proceed before acceptance when labelled non-release; no later
  milestone may be claimed accepted before its predecessor passes staging.
- All compute-intensive verification runs in GitHub Actions. Local work is limited to
  lightweight syntax, unit, lint, type, contract, and diff checks.
- Never inspect, copy, summarize, hash, index, commit, or upload private study inputs.
- Use synthetic data, reserved UUIDs, and disposable tenants only.
- Never commit credentials, provider keys, patient data, tenant data, source text,
  prompts containing source text, or private paths.
- Preserve RLS, transaction-local tenant context, membership-derived authorization,
  provenance, Core Library boundaries, and the ungrounded-answer guard.
- Do not select providers, pricing, curriculum weights, retention periods, or legal
  positions without the required human decision and ADR.
- A CI pass is not staging acceptance. A staging workflow pass is not human approval.

## Current checkpoint

- Remote `main`: `5ac9eff` (`5ac9efff27dbc7aafd31cc3bb6de5748a6fc91b5`).
- CI run `36143277301` is green for that revision.
- The checkout contains the protected OIDC workflow and a new protected runtime-role
  RLS workflow; neither has been dispatched on staging.
- GitHub currently reports no environments, variables, or secrets for this repository.
- M0 is not accepted. Staging OIDC/browser, staging RLS, trace review, and security/
  release approvals remain open.
- No M1–M7 feature has been accepted; a local synthetic preview workspace and API
  exercise M1–M7 seams under ADR 0006.
- This preview implementation is not acceptance evidence and no staging workflow has run.

## A–Z execution queue

Each slice is complete only when its implementation, tests, eval gate where relevant,
runbook, five-minute demo, redacted staging evidence, and security review are complete.

| Slice | Milestone | Outcome | Gate before next slice |
| --- | --- | --- | --- |
| A | M0 | Provision protected `staging` Environment, reviewers, variables, and synthetic secrets | Environment and approval configuration reviewed |
| B | M0 | Dispatch exact-revision staging workflow and capture redacted browser/API evidence | OIDC, membership, role, switch, invalid-token, wrong-audience, logout pass |
| C | M0 | Run protected staging RLS proof as the non-privileged application role | Two-tenant/no-context staging proof and role audit pass |
| D | M0 | Complete redacted staging trace review, security approval, release approval, and M0 evidence record | M0 checklist fully approved |
| E | M1 | Ingestion schema, migrations, private object-key policy, resumable job state | M0 accepted; expand migration and RLS negative tests pass |
| F | M1 | Parsing pipeline steps 1–7 for PDF/DOCX and supported formats | Synthetic 1,000-page/DOCX eval and readiness target pass |
| G | M1 | Library screen, reader, page/bounding-box/figure provenance | Browser acceptance and provenance eval pass |
| H | M1 | Cited `POST /search` with tenant-scoped chunks and figures | Citation, no-result, and cross-tenant negative tests pass |
| I | M2 | Extraction workers, schemas, versioning, and mock/local route boundary | Extraction eval and resumability tests pass |
| J | M2 | Entity resolution and knowledge graph with tenant isolation | Duplicate-concept and cross-tenant graph tests pass |
| K | M2 | Claims, explicit conflicts, curriculum seed/mapping, concept pages | Conflict and coverage evals pass |
| L | M2 | Editor queues for mappings/conflicts with authorization and audit | Role-denial and mutation-audit staging evidence pass |
| M | M3 | Query planner, explicit retrieval stages, hybrid fusion, reranking config | Retrieval eval and latency target pass |
| N | M3 | Grounding judge, citations, figure cards, image-question upload | No-source and ungrounded-output negative tests pass |
| O | M3 | Tutor thread memory, “not in your sources,” tenant-aware cache boundaries | Browser, grounding, and cache-isolation evidence pass |
| P | M4 | Exam-date onboarding, baseline test, planner, phases, Today runner | Planner fixtures and onboarding → Today loop pass |
| Q | M4 | FSRS-style cards, mastery, weekly report, reminders, nightly replan | Scheduling/idempotency and mobile PWA evidence pass |
| R | M5 | SBA, SEQ, image-case, and viva generation with versioned prompts/evals | Item and generator quality gates pass |
| S | M5 | Practice, Exam mode, autosave/resume, grader, review queue, statistics | Disconnect/resume and role/audit staging tests pass |
| T | M6 | Stripe test-mode billing, portal, webhooks, caps, degradation, org/superadmin | Billing/security approval and webhook replay tests pass |
| U | M6 | Export/delete across data, derived artifacts, caches, queues, and observability | Authenticated export/delete and purge evidence pass |
| V | M6 | Load tests, security scans, backup/restore drill, RPO/RTO runbook | Restore timing, load targets, and no high/critical findings pass |
| W | M7 | Certified local-model mode with lower approved thresholds | Local-mode eval and provider/privacy review pass |
| X | M7 | Markdown/Obsidian-compatible export and round-trip links | Synthetic round-trip and provenance tests pass |
| Y | M7 | Mobile wrapper/institution SSO/Core authoring scale work as approved | Each extension has its own human decision and acceptance evidence |
| Z | Release | Final cross-milestone security, privacy, legal, operational, and rollback audit | All milestone evidence and approvals committed; release verdict recorded |

## Definition of done for the overall goal

- M0 through M7 each have a passing staging exit test and committed redacted evidence.
- Every tenant-scoped table has RLS and a non-privileged two-tenant negative test.
- Every agent route has a versioned schema, prompt, fixture, and eval result.
- Every emitted claim/card/question/tutor sentence has a citation or fails closed.
- Long jobs are idempotent, resumable, and expose visible step status.
- Export/delete, backup/restore, cache isolation, object isolation, billing, and local
  mode have explicit evidence where applicable.
- No open critical/high security finding remains.
- Runbooks, five-minute demos, rollback procedures, approvals, and ADRs are current.
- The final release audit records known limitations without private content or secrets.

## Immediate pursuit

The next acceptance slice is A–D: provision and execute the protected M0 staging
gate. Under ADR 0006, local/test-only M1–M7 preview implementation may proceed in
parallel, but it remains non-release and cannot satisfy any A–Z acceptance gate. The
checkout includes Actions-only OIDC and RLS workflows, expanded runtime-role RLS
coverage, callback URL observation, and redacted evidence guidance.
