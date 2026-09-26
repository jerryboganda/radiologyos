# Remaining-work goal: M0 acceptance through M7

Status: **Active goal — M0 production evidence pending; M1–M7 implementation,
eval gates, and runbooks complete as non-release preview**
Scope: all remaining product slices A–Z, in strict milestone order
Owner: autonomous engineering execution, with substantive product/provider decisions preserved
Last reviewed: **2026-09-26**

## Objective

Complete the radiology study platform from the current M0 foundation through M7,
while preserving tenant isolation, provenance, privacy, clinical-safety, legal,
provider, billing, and operational approval boundaries. No later milestone may be
claimed complete before the preceding milestone passes its authoritative exit evidence.

## Non-negotiable execution rules

- Milestone acceptance remains M0 → M7. Under ADR 0006, local/test-only M1–M7 preview
  implementation may proceed before acceptance when labelled non-release; no later
  milestone may be claimed accepted before its predecessor passes its exit evidence.
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
- A CI pass is not release acceptance. A deployment or verification workflow pass is
  evidence for the gate, not a substitute for unresolved product/provider decisions.

## Current checkpoint

- Remote `main`: `5ece59d` is deployed. CI, Build images, Deploy production,
  Verify production RLS and Verify production identity are green on it. From ADR
  0011 onward a push to `main` builds but never deploys; each deploy needs the
  owner's explicit OK and is dispatched for one exact SHA.
- **Priority (ADR 0011): personal-first.** The next work is a real, usable study
  loop for the owner's tenant (upload, parsing, cited search, tutor, planner,
  questions) on the production VPS, with models per ADR 0010.
- **Known blocker:** the public host returns Cloudflare HTTP 525 and the OIDC
  issuer is internal only, so no browser can sign in yet.
- Production runs on the shared platform VPS under ADR 0007. Postgres, Redis, and
  MinIO come from the shared `platform` project; radbrain starts no backing service
  and publishes no host port. See [`runbooks/production-deploy.md`](runbooks/production-deploy.md).
- The live database is at alembic head `20260925_0003`: 8 tables, 7 with RLS
  enforced, runtime role `NOBYPASSRLS` and owning nothing.
- The two-tenant runtime-role RLS proof passes against the deployed database.
- `platform-backup` covers `radiologyos` from the first night; the restore drill is
  verified end to end (RPO 0h, RTO 1s). See [`runbooks/backup-restore.md`](runbooks/backup-restore.md).
- `check-compliance.sh` reports zero violations attributable to radbrain.
- **No M1–M7 feature has been accepted.** M0 is not accepted: the same-commit
  production deployment, OIDC, RLS, backup, security, and compliance evidence still
  needs to be captured and recorded. Preview tests and deployment alone are not
  acceptance evidence.

## A–Z execution queue

Each slice is complete only when its implementation, tests, eval gate where relevant,
runbook, five-minute demo, redacted release evidence, and security review are complete.

Legend: **impl** = implementation and local checks done · **eval** = eval gate exists and
passes · **runbook** = operational runbook exists · **blocked** = needs a substantive
decision or required release evidence.

| Slice | Milestone | Outcome | State |
| --- | --- | --- | --- |
| A | M0 | Deploy one exact candidate revision and capture redacted production health evidence | **blocked** — candidate evidence pending |
| B | M0 | Verify production OIDC identity, membership, role denial, and logout behavior | **blocked** — verification run pending |
| C | M0 | Run production RLS proof as the non-privileged application role | **blocked** — verification run pending |
| D | M0 | Complete same-commit backup, security, compliance, and M0 evidence record | **blocked** — evidence bundle pending |
| E | M1 | Ingestion schema, migrations, private object-key policy, resumable job state | impl · eval · runbook |
| F | M1 | Parsing pipeline steps 1–7 for PDF/DOCX and supported formats | impl · eval · runbook (3 steps stay `skipped` by design) |
| G | M1 | Library screen, reader, page/bounding-box/figure provenance | impl · eval · runbook (bbox is a zero rectangle) |
| H | M1 | Cited `POST /search` with tenant-scoped chunks and figures | impl · eval · runbook |
| I | M2 | Extraction workers, schemas, versioning, and mock/local route boundary | impl · eval · runbook |
| J | M2 | Entity resolution and knowledge graph with tenant isolation | impl · eval · runbook (resolution not attempted) |
| K | M2 | Claims, explicit conflicts, curriculum seed/mapping, concept pages | impl · eval · runbook (curriculum mapping absent) |
| L | M2 | Editor queues for mappings/conflicts with authorization and audit | impl · eval · runbook |
| M | M3 | Query planner, explicit retrieval stages, hybrid fusion, reranking config | impl · eval · runbook (no embedding, no reranker) |
| N | M3 | Grounding judge, citations, figure cards, image-question upload | impl · eval · runbook (lexical judge, no image upload) |
| O | M3 | Tutor thread memory, “not in your sources,” tenant-aware cache boundaries | impl · eval · runbook |
| P | M4 | Exam-date onboarding, baseline test, planner, phases, Today runner | impl · eval · runbook (baseline `not_implemented`) |
| Q | M4 | FSRS-style cards, mastery, weekly report, reminders, nightly replan | impl · eval · runbook (no report, reminders, or nightly job) |
| R | M5 | SBA, SEQ, image-case, and viva generation with versioned prompts/evals | impl · eval · runbook (SBA only; no versioned prompt registry) |
| S | M5 | Practice, Exam mode, autosave/resume, grader, review queue, statistics | impl · eval · runbook (no review queue UI) |
| T | M6 | Stripe test-mode billing, portal, webhooks, caps, degradation, org/superadmin | **parked** (ADR 0011) — in-memory service and routes exist but answer 404 unless `BILLING_ENABLED=true`; plan values are placeholders pending an owner pricing decision |
| U | M6 | Export/delete across data, derived artifacts, caches, queues, and observability | impl · eval · runbook (purge verified; release routes stay 501) |
| V | M6 | Load tests, security scans, backup/restore drill, RPO/RTO runbook | impl · eval · runbook (load + scans + drill all green) |
| W | M7 | Certified local-model mode with lower approved thresholds | **out of scope** — removed by ADR 0009 |
| X | M7 | Markdown/Obsidian-compatible export and round-trip links | impl · eval · runbook (Markdown only, no import) |
| Y | M7 | Mobile wrapper/institution SSO/Core authoring scale work as approved | **out of scope** — mobile and institution SSO removed by ADR 0009 |
| Z | Release | Final cross-milestone security, privacy, legal, operational, and rollback audit | **blocked** — needs D and all milestone evidence |

## Eval gates

Each gate is a standalone pytest module run by CI, using synthetic data only.

| Gate | Covers | Tests |
| --- | --- | --- |
| `evals/checks/test_m1_library.py` | E, F, G, H | 24 |
| `evals/checks/test_m2_knowledge.py` | I, J, K, L | 30 |
| `evals/checks/test_m3_tutor.py` | M, N, O | 19 |
| `evals/checks/test_m4_planner.py` | P, Q | 39 |
| `evals/checks/test_m5_assessment.py` | R, S | 28 |
| `evals/checks/test_m6_ops.py` | U, V | 20 |
| `evals/checks/test_m6_billing.py`, `test_m6_billing_http.py` | T | 52 |
| `evals/checks/test_m7_portability.py` | W, X | 15 |

Plus `test_preview_determinism.py`, `test_scaffolding.py`, and
`test_rls_live.py` (the last is opt-in and runs against a live database in
`Verify production RLS`).

## Definition of done for the overall goal

- M0 through M7 each have passing exit evidence and committed redacted records.
- Every tenant-scoped table has RLS and a non-privileged two-tenant negative test.
- Every agent route has a versioned schema, prompt, fixture, and eval result.
- Every emitted claim/card/question/tutor sentence has a citation or fails closed.
- Long jobs are idempotent, resumable, and expose visible step status.
- Export/delete, backup/restore, cache isolation, object isolation, billing, and the
  approved v1 portability scope have explicit evidence where applicable.
- No open critical/high security finding remains.
- Runbooks, five-minute demos, rollback procedures, approvals, and ADRs are current.
- The final release audit records known limitations without private content or secrets.

## Immediate pursuit

Personal-first (ADR 0011): fix public sign-in, then replace the in-memory preview
with the real pipeline for the owner's tenant (storage, RLS tables, worker jobs,
parsing, embeddings, retrieval, tutor, planner, questions). The remaining
acceptance work is A–D, then the product-decision slices, then Z. A–D require one exact production candidate and its automated evidence;
provider, privacy, pricing, curriculum, and legal decisions still require explicit
decisions with ADRs. Those are recorded as open rather than simulated, and the
implementation deliberately refuses instead of faking them.
