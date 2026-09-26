# Remaining-work goal: M0 acceptance through M7

> **2026-09-26:** [`completion-plan.md`](completion-plan.md) is the tracking document:
> it has the audited gap list (G1–G35) and the phased plan. This file keeps the A–Z
> slice history and the definition of done; the checkpoint below is refreshed.

Status: **Active goal — M0 evidence record pending; durable M1–M6 slices run in
production for the owner's tenant; nothing accepted yet (see `completion-plan.md`)**
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

- Deployed revision: `0a18f2c`. CI, Build images, Deploy production, Verify
  production RLS and Verify production identity are green on it. A push to `main`
  builds but never deploys (ADR 0011); each deploy needs the owner's explicit OK and
  is dispatched for one exact SHA.
- **Priority (ADR 0011): personal-first.** A usable study loop for the owner's
  tenant on the production VPS, with models per ADR 0010.
- Sign-in works in the browser. The OIDC issuer is public
  (`https://radiologyos.polytronx.com/auth/realms/radbrain`); JWKS and the token
  exchange stay on the internal Keycloak address.
- Production runs on the shared platform VPS under ADR 0007; see
  [`runbooks/production-deploy.md`](runbooks/production-deploy.md). The in-memory
  preview surface was removed (ADR 0031); its paths answer 404.
- The live database is at alembic head `20260926_0014` with 38 tenant tables, all
  ENABLE + FORCE RLS. The runtime role is `NOBYPASSRLS` and owns nothing.
- Schema evidence is derived, not hand-written (ADR 0022). The production RLS proof
  now covers every `tenant_id` table from the catalog, and the restore drill asserts
  the head, RLS and extensions. Both need a fresh run on the deployed head before
  they count as evidence.
- Nightly platform dumps and an off-host Google Drive copy (databases and objects)
  exist; see [`runbooks/backup-restore.md`](runbooks/backup-restore.md).
- **No M1–M7 feature has been accepted.** M0 is not accepted: it needs its same-SHA
  evidence record in `docs/evidence/m0.md` (generated with
  `scripts/evidence_record.py`), plus the drill output and compliance result. Eval
  gates and deployment alone are not acceptance evidence.

## A–Z execution queue

Each slice is complete only when its implementation, tests, eval gate where relevant,
runbook, five-minute demo, redacted release evidence, and security review are complete.

Legend: **durable** = persistent, RLS-proved, deployed for the owner tenant (ADR 0011) · **impl** = implementation and local checks done · **eval** = eval gate exists and
passes · **runbook** = operational runbook exists · **blocked** = needs a substantive
decision or required release evidence.

| Slice | Milestone | Outcome | State |
| --- | --- | --- | --- |
| A | M0 | Deploy one exact candidate revision and capture redacted production health evidence | **blocked** — candidate evidence pending |
| B | M0 | Verify production OIDC identity, membership, role denial, and logout behavior | **impl** — `verify-oidc.py` checks logout, tenant-switch denial and role denial (ADR 0022); run on the deployed head pending |
| C | M0 | Run production RLS proof as the non-privileged application role | **impl** — catalog-driven proof over every `tenant_id` table (ADR 0022); run on the deployed head pending |
| D | M0 | Complete same-commit backup, security, compliance, and M0 evidence record | **blocked** — asserting drill ready; `docs/evidence/m0.md` pending |
| E | M1 | Ingestion schema, migrations, private object-key policy, resumable job state | **durable** (0004, ADR 0012) — tenant-prefixed object keys, jobs/job_steps written, resumable, 25-page run budget; live RLS proof |
| F | M1 | Parsing pipeline steps 1–7 for PDF/DOCX and supported formats | **durable** — pdfium render + LibreOffice for DOCX/PPTX (repack fallback), native text first, Opus 5.5 `page_parse` vision pass; 393 owner sources ingested |
| G | M1 | Library screen, reader, page/bounding-box/figure provenance | **durable** — web Library + reader with real normalised bboxes, figure crops, 1:1 zoom, cited-block deep links |
| H | M1 | Cited `POST /search` with tenant-scoped chunks and figures | **durable** — `POST /v1/library/search` tsvector + pgvector RRF, cited hits and figures, owner-scoped |
| I | M2 | Extraction workers, schemas, versioning, and mock/local route boundary | **durable** (0008, ADR 0016) — `knowledge_extract` with verbatim evidence spans enforced in code; resumable worker |
| J | M2 | Entity resolution and knowledge graph with tenant isolation | **durable** — alias + trigram resolution (0.92 merge, 0.80–0.92 flagged) |
| K | M2 | Claims, explicit conflicts, curriculum seed/mapping, concept pages | **durable** — claims, explicit `knowledge_conflicts`, curriculum mapping (<0.7 → review) |
| L | M2 | Editor queues for mappings/conflicts with authorization and audit | **durable** — conflict resolve, weight approval, and the curriculum-mapping review queue (`/knowledge/review`, ADR 0018) are audited APIs + UI |
| M | M3 | Query planner, explicit retrieval stages, hybrid fusion, reranking config | **durable** — explicit lexical + dense stages fused by RRF; reranker not yet configured |
| N | M3 | Grounding judge, citations, figure cards, image-question upload | **durable** (0005, ADR 0013) — code-verified citations, allow-listed web fallback, semantic grounding judge on by default; image-question upload still missing (G7) |
| O | M3 | Tutor thread memory, “not in your sources,” tenant-aware cache boundaries | **durable** — persisted threads, explicit not-found response, no cross-tenant cache |
| P | M4 | Exam-date onboarding, baseline test, planner, phases, Today runner | **durable** (0006, ADR 0014) — exam-date onboarding, phases, sized daily plan, baseline test (0010); Today session runner still missing (G4) |
| Q | M4 | FSRS-style cards, mastery, weekly report, reminders, nightly replan | **durable** — in-house FSRS-5, mastery, push reminders (0009), weekly report and nightly replan jobs (0010) |
| R | M5 | SBA, SEQ, image-case, and viva generation with versioned prompts/evals | **durable** (0007, ADR 0015) — SBA/SEQ/image-case/viva generation with checker gate and versioned prompts |
| S | M5 | Practice, Exam mode, autosave/resume, grader, review queue, statistics | **durable** — exam mode with server deadline, revision autosave, idempotent submit, per-topic results; mixed SBA and free-text papers with a grader (0011) |
| T | M6 | Stripe test-mode billing, portal, webhooks, caps, degradation, org/superadmin | **parked** (ADR 0011) — in-memory service and routes exist but answer 404 unless `BILLING_ENABLED=true`; plan values are placeholders pending an owner pricing decision |
| U | M6 | Export/delete across data, derived artifacts, caches, queues, and observability | **durable** (0012, ADR 0018) — export ZIP job with 7-day expiry, resumable account delete across rows, embeddings, and objects, legal-hold aware; live proof in CI. Scheduled 24-month retention purge built, **off by default** (0014, ADR 0020; dry-run command, audited, legal-hold/Core/exempt-safe; live proof in CI). Open: IdP session revocation, provider-log purge, backup expiry |
| V | M6 | Load tests, security scans, backup/restore drill, RPO/RTO runbook | impl · eval · runbook (load + scans + drill all green) |
| W | M7 | Certified local-model mode with lower approved thresholds | **out of scope** — removed by ADR 0009 |
| X | M7 | Markdown/Obsidian-compatible export and round-trip links | impl · eval · runbook (Markdown only, no import) |
| Y | M7 | Mobile wrapper/institution SSO/Core authoring scale work as approved | **out of scope** — mobile and institution SSO removed by ADR 0009 |
| Z | Release | Final cross-milestone security, privacy, legal, operational, and rollback audit | **blocked** — needs D and all milestone evidence |

## Eval gates

Each gate is a standalone pytest module run by CI, using synthetic data only. Since
ADR 0031 every gate drives the durable services (in-memory repositories, recording
sessions, fake model transports); the row-level proofs are the `*_live.py` modules.

| Gate | Covers | Tests |
| --- | --- | --- |
| `evals/checks/test_m1_library.py` (+ `apps/api/tests/test_library_api.py`, 21) | E, F, G, H | 17 |
| `evals/checks/test_m2_knowledge.py` | I, J, K, L | 33 |
| `evals/checks/test_m3_tutor.py` | M, N, O | 33 |
| `evals/checks/test_m4_planner.py` | P, Q | 49 |
| `evals/checks/test_m5_assessment.py` | R, S | 27 |
| `evals/checks/test_m6_ops.py` | U, V | 13 |
| `evals/checks/test_m6_billing.py`, `test_m6_billing_http.py` | T | 52 |
| `evals/checks/test_m7_portability.py` | W, X | 17 |

Plus `test_determinism.py` (10), `test_scaffolding.py`, and the opt-in
`*_live.py` proofs, which CI runs against a migrated database. `test_rls_live.py`
also runs against production in `Verify production RLS`. It covers every
`tenant_id` table from the catalog (ADR 0022).

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

Follow [`completion-plan.md`](completion-plan.md). Phase 1 accepts M0: run the
extended identity and RLS verification and the asserting restore drill on the deployed
head, then write `docs/evidence/m0.md`. After that come the product-decision phases,
then Z. Provider, privacy, pricing, curriculum and legal decisions still need explicit
decisions with ADRs. They stay open rather than simulated, and the implementation
refuses rather than fakes them.
