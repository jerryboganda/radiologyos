# Remaining-work goal: M0 acceptance through M7

> **2026-09-26:** [`completion-plan.md`](completion-plan.md) is the tracking document:
> it has the audited gap list (G1–G35) and the phased plan. This file keeps the A–Z
> slice history and the definition of done; the checkpoint below is refreshed.

Status: **Active goal — every in-scope slice is implemented and merged on `main`
(billing parked); the next deploy and the M0 evidence record are pending; nothing
accepted yet (see `completion-plan.md`)**
Scope: all remaining product slices A–Z, in strict milestone order
Owner: autonomous engineering execution, with substantive product/provider decisions preserved
Last reviewed: **2026-09-26**

## Objective

Complete the radiology study platform from the current M0 foundation through M7,
while preserving tenant isolation, provenance, privacy, clinical-safety, legal,
provider, billing, and operational approval boundaries. No later milestone may be
claimed complete before the preceding milestone passes its authoritative exit evidence.

## Non-negotiable execution rules

- Milestone acceptance remains M0 → M7. The ADR 0006 preview surface was removed
  (ADR 0031); no later milestone may be claimed accepted before its predecessor
  passes its exit evidence. Release scope is fixed by ADR 0034.
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
- `main` is ahead of production. Completion-plan work packages A–J (ADR 0022–0032)
  and ADR 0033 page reading are merged with migrations `20260926_0015` through
  `20260926_0104`, but they are **not deployed**. Their tenant tables have ENABLE +
  FORCE RLS and runtime-role two-tenant proofs in CI.
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
  evidence record in `docs/evidence/m0.md` (a TODO stub today; format in
  `docs/evidence/README.md`, run table from `scripts/evidence_record.py`), plus the
  drill output and compliance result. Eval gates and deployment alone are not
  acceptance evidence.
- Five-minute demo scripts exist for M0–M7 in `docs/demos/`. Running them is not
  evidence until a record cites the run.

## A–Z execution queue

Each slice is complete only when its implementation, tests, eval gate where relevant,
runbook, five-minute demo, redacted release evidence, and security review are complete.

Legend: **durable** = persistent, RLS-proved, and deployed for the owner tenant at
`0a18f2c` (ADR 0011) · **merged** = implemented, tested (unit, HTTP, eval gate, CI
runtime-role live proof) and merged on `main`, not yet deployed · **pending
evidence** = needs the next deploy (owner OK) and a same-SHA record in
`docs/evidence/` · **parked** / **out of scope** = excluded from the release by an ADR
(ADR 0034). No slice is accepted until its milestone's record is.

| Slice | Milestone | Outcome | State |
| --- | --- | --- | --- |
| A | M0 | Deploy one exact candidate revision and capture redacted production health evidence | **pending evidence** — next deploy needs the owner's OK; record stub `docs/evidence/m0.md` |
| B | M0 | Verify production OIDC identity, membership, role denial, and logout behavior | **merged** — `verify-oidc.py` checks logout, tenant-switch denial and role denial (ADR 0022); **pending evidence** on the deployed head |
| C | M0 | Run production RLS proof as the non-privileged application role | **merged** — catalog-driven proof over every `tenant_id` table (ADR 0022); **pending evidence** on the deployed head |
| D | M0 | Complete same-commit backup, security, compliance, and M0 evidence record | **pending evidence** — asserting drill merged; record format in `docs/evidence/README.md`; M0 demo `docs/demos/m0-foundation.md` |
| E | M1 | Ingestion schema, migrations, private object-key policy, resumable job state | **durable** (0004, ADR 0012) — tenant-prefixed object keys, jobs/job_steps, resumable, 25-page run budget; live RLS proof |
| F | M1 | Parsing pipeline steps 1–7 for PDF/DOCX and supported formats | **durable**, depth **merged** — pdfium + LibreOffice, text-first PDFs (ADR 0027), Sonnet 5 page reading with Opus 5.5 fallback (ADR 0033), tables (ADR 0030); 393 owner sources ingested, vision pass awaits the one-time reprocess |
| G | M1 | Library screen, reader, page/bounding-box/figure provenance | **durable**, depth **merged** — reader with bboxes, figure crops, 1:1 zoom, deep links; Tables tab, Re-process, "Ask about this page" (ADR 0025, ADR 0030) |
| H | M1 | Cited `POST /search` with tenant-scoped chunks and figures | **durable**, depth **merged** — tsvector + pgvector RRF, cited hits, figures and tables, reranked order (ADR 0028) |
| I | M2 | Extraction workers, schemas, versioning, and mock/local route boundary | **durable** (0008, ADR 0016) — verbatim evidence spans enforced in code; user-turn templates in versioned prompt YAML (ADR 0032) **merged** |
| J | M2 | Entity resolution and knowledge graph with tenant isolation | **durable**, depth **merged** — alias + trigram resolution; Resolver agent merges duplicates with undo (ADR 0030) |
| K | M2 | Claims, explicit conflicts, curriculum seed/mapping, concept pages | **durable**, depth **merged** — curriculum topic tree and blueprints (ADR 0023, owner approval pending), cited concept notes, Conflict agent and "trust source", concept map (ADR 0030) |
| L | M2 | Editor queues for mappings/conflicts with authorization and audit | **durable**, depth **merged** — audited conflict, weight and mapping queues; duplicate-merge review with undo (ADR 0030) |
| M | M3 | Query planner, explicit retrieval stages, hybrid fusion, reranking config | **merged** — Voyage `rerank-2.5` with its own 195M cap, graph expansion, intent routing (ADR 0028; reranker is M3, ADR 0034); production eval pending (G32) |
| N | M3 | Grounding judge, citations, figure cards, image-question upload | **durable**, depth **merged** — draft streaming (off by default), image-question upload, similar figures, figure quiz (ADR 0025) |
| O | M3 | Tutor thread memory, “not in your sources,” tenant-aware cache boundaries | **durable**, depth **merged** — rolling thread summary, never cited (ADR 0025) |
| P | M4 | Exam-date onboarding, baseline test, planner, phases, Today runner | **durable**, depth **merged** — Today session runner, blueprints for exams (ADR 0023, ADR 0024) |
| Q | M4 | FSRS-style cards, mastery, weekly report, reminders, nightly replan | **durable**, depth **merged** — weakness loop, cloze and image cards, heatmap, projection, calibration, keyboard shortcuts (ADR 0024, ADR 0029) |
| R | M5 | SBA, SEQ, image-case, and viva generation with versioned prompts/evals | **durable**, depth **merged** — multi-turn viva examiner, staged TOACS image case (ADR 0026), claim-based SBA with graph distractors (ADR 0029) |
| S | M5 | Practice, Exam mode, autosave/resume, grader, review queue, statistics | **durable**, depth **merged** — results review with time per item, jump to source, grade disputes (ADR 0029) |
| T | M6 | Stripe test-mode billing, portal, webhooks, caps, degradation, org/superadmin | **parked** — out of release scope until the owner sets pricing (ADR 0011, ADR 0034); routes answer 404 unless `BILLING_ENABLED=true`; gates kept as regression only |
| U | M6 | Export/delete across data, derived artifacts, caches, queues, and observability | **durable**, depth **merged** — export ZIP with vault, resumable delete, retention purge off by default (ADR 0018, ADR 0020); IdP session revocation, provider-log and backup-expiry procedure (ADR 0032) |
| V | M6 | Load tests, security scans, backup/restore drill, RPO/RTO runbook | **merged** — model ledger, metrics, rate limits, audit coverage, MFA script (ADR 0032), asserting drill (ADR 0022); applying MFA and the Actions load check need the owner |
| W | M7 | Certified local-model mode with lower approved thresholds | **out of scope** — removed by ADR 0009; M7 redefined by ADR 0034 |
| X | M7 | Markdown/Obsidian-compatible export and round-trip links | **merged** — durable vault in the account export, read back by `vault_links.read_vault` (ADR 0031); this is M7 (ADR 0034); import not in scope |
| Y | M7 | Mobile wrapper/institution SSO/Core authoring scale work as approved | **out of scope** — mobile and institution SSO removed by ADR 0009 |
| Z | Release | Final cross-milestone security, privacy, legal, operational, and rollback audit | **pending evidence** — needs A–D, then M1–M7 records, demos (all written) and G32 eval runs |

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
| `evals/checks/test_m6_billing.py`, `test_m6_billing_http.py` | T (regression only, not release evidence; ADR 0034) | 52 |
| `evals/checks/test_m7_portability.py` | X, and the online-only provider boundary that replaced W | 17 |

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
- Export/delete, backup/restore, cache isolation, object isolation, and the v1
  portability scope (the vault export, ADR 0034) have explicit evidence. Billing is
  out of release scope until the owner sets pricing (ADR 0034).
- No open critical/high security finding remains.
- Runbooks, five-minute demos, rollback procedures, approvals, and ADRs are current.
- The final release audit records known limitations without private content or secrets.

## Immediate pursuit

Follow [`completion-plan.md`](completion-plan.md). The code for every in-scope slice
is merged, so what remains is evidence, in order:

1. The owner approves a deploy of one `main` SHA. Then run the extended identity and
   RLS verification and the asserting restore drill on that head, and fill in
   `docs/evidence/m0.md` (format: `docs/evidence/README.md`).
2. The owner's pending decisions: approve the curriculum and blueprints, time the
   library reprocess, apply admin MFA, and decide on draft streaming.
3. M1–M7 records in order, each with its demo from `docs/demos/` and, where the
   milestone has agent routes, recorded real-model eval runs (G32).
4. Slice Z, the final audit. Provider, privacy, pricing, curriculum and legal decisions still need explicit
decisions with ADRs. They stay open rather than simulated, and the implementation
refuses rather than fakes them.
