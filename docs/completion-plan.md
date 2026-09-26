# Completion plan — radbrain to 100%

Status: **proposed, awaiting owner review** · Written: 2026-09-26 · Baseline SHA: `0a18f2c`
Supersedes the status tables in [`remaining-work.md`](remaining-work.md), which are stale.

## What "100% complete" means here

The owner's agreed scope is the baseline spec **minus** what ADRs removed: local-model
mode, mobile wrapper and institution SSO (ADR 0009), and billing (parked, ADR 0011).
It is complete when both of these hold:

1. **Product complete:** every in-scope spec feature works end to end, durable and
   RLS-protected, on the owner's real library in production.
2. **Release complete:** M0–M7 each have committed exit evidence (ADR 0008 style:
   automated, same SHA), a five-minute demo, and no open critical/high finding.

## Where we are (audited 2026-09-26)

| Area | State |
| --- | --- |
| Infrastructure, auth, RLS, deploy chain | Live and green on `0a18f2c`. 38 tenant tables, all FORCE RLS with CI two-tenant proofs. |
| Library | 393 sources and 62K blocks parsed natively and keyword-searchable. **0 of 6,949 pages vision-parsed, 0 figures, 12 of 5,437 chunks embedded.** |
| AI features (knowledge, weights, tutor, cards, questions, exams, plan) | Code is built and tested, but **0 rows in production**, because `CLAUDE_CODE_OAUTH_TOKEN` is not installed. |
| Curriculum | 16 systems only, marked `placeholder_unvalidated`. No topic tree and no IMM/TOACS/FRCR packs. |
| Release evidence | No evidence records. `docs/demos/` is empty. Production RLS proof covers 7 of 38 tables. Restore drill is from the 0003 schema and asserts nothing. |
| Security settings | No branch protection on `main`. Dependabot alerts off. No CodeQL. Preview surface (in-memory, outside RLS) is **enabled in production**. |

## Gap inventory

### Blocking everything AI

- G1. The Claude token is not installed. The vision pass, figures, embeddings, knowledge,
  weights, tutor, cards and questions cannot run.

### Exam-critical product gaps (highest study value)

- G2. **Curriculum depth:** a topic and subtopic tree for FCPS-II, IMM, TOACS and FRCR. The
  planner, mapping and mastery only reach system level today.
- G3. **Exam blueprints** per target: counts, timing, per-system mix, negative marking.
- G4. **Today session runner:** learn → review → SBA block → viva prompt, resumable, with
  completion feeding the replan.
- G5. **Weakness loop:** a wrong answer creates or resets a card and re-tests within two days.
- G6. **Multi-turn viva examiner** (Viva agent, escalation, transcript, cited teaching points)
  and a **staged TOACS image case** (describe → findings → diagnosis → DDx → next step).
- G7. **Tutor image upload:** ask about a spotter image. Also "quiz me on this figure" and
  "similar figures".
- G8. **Token streaming** in the tutor. Today the SSE stream carries stage status only.
- G9. **Cards from verified claims and figures:** cloze and image cards, not only Q/A from chunks.
- G10. **Progress:** a coverage heatmap by system and topic, a days-remaining projection
  (pace, hours needed), and confidence capture with calibration.
- G11. **Exam results review:** time per item, a jump to the source for wrong answers, and grade
  disputes.
- G12. **Keyboard shortcuts:** 1–4 card ratings and A–E options.

### Quality gaps

- G13. **Retrieval:** no reranker, no graph expansion, no intent routing (compare, DDx, show-me).
- G14. **Knowledge depth:**
  - No Synthesis agent, so there are no cited concept notes.
  - No Resolver agent, so duplicate concepts across books are not merged.
  - No Conflict agent and no "trust source" option.
  - No graph visual.
- G15. **Parsing:** tables are skipped, and there is no source "re-process" button. The Reader
  has no "ask about this page".
- G16. **Question generation from claims**, with distractors from graph neighbours.
- G17. **Thread memory** is the raw recent history, with no rolling summary.

### Hardening gaps

- G18. **Preview surface:** turn it off in production, then remove about 1,800 lines of
  in-memory code. Re-point the M1 eval gate at the real library. *Implemented (WP-I,
  ADR 0031): removed; M1–M7 gates re-pointed at durable code; durable vault export.*
- G19. **Tests:**
  - No HTTP tests for `/v1/library/*`, notifications or alert ack.
  - No tests for `security/context.py`, web `auth.ts` or `hooks.server.ts`, or the worker beat
    jobs.
  - No E2E flows in Actions.
  - *Implemented (WP-I): HTTP, security-context, worker, and web helper tests; the
    `E2E` workflow runs the browser flow on the Compose stack. The E2E run in Actions
    is still to be observed green.*
- G20. **Model usage ledger:** an `llm_calls` table with a per-route usage view, caps and alerts.
  Subscription limits are opaque today.
- G21. **Observability:** trace IDs, metrics and error tracking. Today there is only a JSON
  request log.
- G22. **Rate limits** per user and tenant (Redis token bucket).
- G23. **Audit log coverage:** about 5 call sites today. Every mutating endpoint should write one.
- G24. **MFA** for admin roles in Keycloak.
- G25. **Prompt hygiene:**
  - User-turn templates are built inline in 5 places; move them into versioned prompt files.
  - Retire the 4 placeholder route prompts.
  - Settings-only model and binary config.
- G26. **Hard-rule debt:**
  - Functions over 60 lines: `test_rls_live` 333, `verify-oidc` 241.
  - Empty `infra/helm` and `infra/api` directories.
  - Bandit and mypy do not cover `packages/`.
  - *WP-I: CI mypy and Bandit now cover `packages/` (clean). The helm/api directories
    are gone; the two long functions were split earlier. Remaining over 60 lines:
    `apps/api/migrations/sql.py::split_sql_statements` and released migrations.*
- G27. **Real account data:** `/v1/me` and `/v1/tenants/switch` return stub data.
  *Implemented (WP-I): both answer from the membership row; a foreign switch is 403.*

### Release-evidence gaps

- G28. ADR 0008 hard-codes "head 0003, 8/7 tables". Replace it with a derived check, and
  enforce the required checks with branch protection.
- G29. The production RLS proof must cover all tenant tables, not 7.
- G30. The restore drill must assert head, tables and RLS, run for the current head, and
  include Keycloak and an object sample from the off-host copy.
- G31. `verify-oidc.py` must also check logout, tenant-switch denial and role denial.
- G32. **Evals:** golden sets and real-model runs per route with recorded results. Today every
  eval uses synthetic fixtures and fakes.
- G33. **Per-milestone records:** five-minute demos and evidence records for M0–M7. Also run the
  load check in Actions and record a security disposition for the dev-only Playwright advisories.
- G34. **Stale docs:**
  - `remaining-work`, `CONTEXT`, `SPEC` status and milestones (staging, M7 = local mode),
    `docs/README` ADR index.
  - Production-deploy limitations and backup evidence.
- G35. **Data-rights leftovers:** IdP session revocation on delete, provider-log purge, backup
  expiry.

## Execution plan

Each phase ends with its gate. The usual loop applies: tests first, local checks, push to
`main`, green CI/Build, then **deploy only with the owner's OK**.

### Phase 0 — Unblock and close exposure (day 1)

| # | Work | Who |
| --- | --- | --- |
| 0.1 | Install `CLAUDE_CODE_OAUTH_TOKEN` (`set-claude-token.sh`), recreate api and worker, run `bulk --reprocess` **once**, and watch the vision → embed → figures progress | Owner token, then me |
| 0.2 | `PREVIEW_ENABLED=false` in production. Fix `wire-oidc.sh` and the docs that contradict it | Me, owner OK |
| 0.3 | Branch protection on `main` requiring CI. Enable Dependabot alerts. Add CodeQL | Me, owner OK |
| 0.4 | Confirm the off-host backup is scheduled and its first success marker exists | Peer session 19 |

**Gate:** vision parsing is progressing, preview returns 404 in production, and `main` is protected.

### Phase 1 — Accept M0 (days 1–3)

- **G28:** ADR 0022 amending ADR 0008 with the derived migration check and branch-protection
  enforcement.
- **G29:** the production RLS proof covers every table that has a `tenant_id`, driven by the
  catalog so new tables are included automatically. Split the 333-line function (G26).
- **G30:** the hardened restore drill, run on the current head, with RPO/RTO recorded.
- **G31:** the extended OIDC verification.
- **G34:** refresh the stale docs. Replace `remaining-work.md` tables with this plan's tracking.
- **M0 evidence record** in `docs/evidence/m0.md`: run IDs, image digests, drill output,
  compliance result. Plus the M0 five-minute demo.

**Gate: M0 accepted** under the amended ADR.

### Phase 2 — Curriculum and blueprints (days 2–6, needs owner input)

- **Curriculum packs:** topics and subtopics for FCPS-II, IMM, TOACS and FRCR 2A/2B, built from
  public syllabi and the owner's past papers. The owner reviews them in the existing review
  queue.
- **Weights:** derived from past-paper frequency once the vision pass has read the papers. The
  owner approves them in the UI (the flow already exists).
- **Blueprint entity (G3):** per-exam defaults for counts, time, per-system mix and negative
  marking, used by exam creation.

**Gate:** approved curriculum and weights, and exams built from a blueprint.

### Phase 3 — Daily study loop (week 2)

- **G4:** Today session runner.
- **G5:** weakness loop.
- **G9:** cloze and image cards.
- **G12:** keyboard shortcuts.
- **G10:** heatmap, projection and calibration.
- **G11:** results review and disputes.

Unit, HTTP and live-RLS tests for every new table.

**Gate:** M4 slices durable in production and used by the owner for a full day.

### Phase 4 — Tutor quality (week 2–3)

- **G8:** token streaming.
- **G7:** image question upload.
- **G13:** reranker, graph expansion and intent routing.
- **G17:** rolling thread memory.
- **G15:** "ask about this page".

**Gate:** tutor golden-set eval (G32) passes its thresholds with real model runs recorded.

### Phase 5 — TOACS, viva and FRCR practice (week 3)

- **G6:** the Viva agent with a multi-turn session, escalation, stop rules and a cited
  transcript.
- **G6:** the staged image case.
- **G16:** claim-based question generation.
- A grader golden set.

**Gate:** M5 demo — a full mock TOACS and SBA paper from a blueprint.

### Phase 6 — Knowledge depth (week 3–4)

- **G14:** Synthesis, Resolver and Conflict agents, the trust-source decision, and a graph
  visual on concept pages.
- **G15:** table extraction and the re-process button.

Each new agent ships with a versioned prompt, schema, fixture and eval.

**Gate:** M2 demo on real concepts, with cited notes and resolved duplicates.

### Phase 7 — Hardening (week 4, parallel where possible)

- **G18:** remove the preview surface (ADR).
- **G19:** test backfill and Playwright E2E in Actions.
- **G20:** `llm_calls` ledger with usage alerts.
- **G21:** observability.
- **G22:** rate limits.
- **G23:** audit coverage.
- **G24:** MFA.
- **G25–G27:** clean-ups.
- **G35:** data-rights leftovers.
- The load check run in Actions.

**Gate:** no open critical/high finding, CI coverage not reduced, E2E green.

### Phase 8 — Formal acceptance M1–M7 and release audit (week 5)

- **Scope ADRs:**
  - M7 is redefined as a durable Markdown/Obsidian-compatible export with round-trip links
    (ADR 0009 removed local mode).
  - Billing is out of release scope until pricing is decided.
- **G32:** golden sets and recorded real-model eval runs for every agent route.
- **G33:** per-milestone evidence records and demos in `docs/evidence/` and `docs/demos/`.
- **Slice Z:** the final security, privacy, operational and rollback audit, with known limits.

**Gate:** the definition of done in `remaining-work.md` holds for every milestone.

## Decisions the owner must make (CLAUDE.md "stop and ask")

1. **Install the Claude token.** Nothing AI-driven can run until it is on the server.
2. **Curriculum and exam blueprints.** Approve the topic trees, weights and exam formats
   (question counts, time, negative marking). The draft comes from syllabi plus your past
   papers.
3. **Reranker model.** Recommended: Voyage `rerank-2.5`, the same account with a separate free
   quota, and the same hard-stop pattern. This is a new concrete model, so it needs your OK.
4. **Production changes:**
   - switch off preview;
   - branch protection, Dependabot and CodeQL;
   - run the load check against production.
5. **Scope ADRs.** M7 becomes the Markdown export, and billing stays out of the release.
6. **Deploys.** Each deploy still needs your explicit OK (ADR 0011). The alternative is to
   approve "deploy each green phase gate".
