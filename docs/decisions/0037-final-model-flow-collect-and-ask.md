# 0037 — Final bulk model flow, collect & ask, and a pausable pipeline

- Status: accepted (owner decisions, 2026-09-26: "keep this flow, make this final, save it")
- Amends: ADR 0035 (model rules), ADR 0027 (quality gates), ADR 0016 (knowledge extraction)

## Why

A judged test pass on one 19-slide deck, with GPT-6 Luna, showed failure points beyond the figure
diagnoses fixed in ADR 0036:
- evidence spans that only quoted exam questions;
- claims that said more than their evidence;
- claims that only make sense on the slide ("The diagnosis is X");
- a source error passed on as fact ("medial neck" for a radial neck fracture);
- citations naming the chunk's first page instead of the evidence page.

The pipeline itself would also have failed a full-library run:
- An item that both Luna and Sol answered below a quality gate paused its whole source for good,
  and re-spent ChatGPT quota every retry.
- A ChatGPT quota hit could fall through to the Claude step.
- There was no way to pause, stop or relaunch the run.
- A lost knowledge task was never queued again.

## Decision

- **The model flow for all bulk work** (pages, figures, every knowledge agent):
  1. GPT-6 Luna at **max** reasoning (the knowledge agents keep the Fast tier).
  2. GPT-6 Sol at high, when Luna fails or its answer is ambiguous.
  3. Claude Opus 5.5 high, **only after the owner approves**.
- **Quality gates return either kind of reason:**
  - A hard reason can escalate all the way.
  - A reason made with `soft()` asks Sol for a second opinion only. Sol's answer is kept and the
    owner is never asked. Examples: a doubted source statement, context-free claims, a
    low-confidence figure.
- **Collect & ask (the owner's choice).** When only the approval-gated target is left, the
  gateway never calls it.
  - If a best free answer exists, it is returned with `result.escalation`: pages and figures keep
    it, and a knowledge chunk is held with nothing stored.
  - If there is no answer, `OwnerApprovalRequired` is raised and the job carries on.
  - Either way, the item goes into `model_escalations` (tenant RLS) and the owner gets one amber
    alert and push notification.
  - Approving (Settings or the pipeline CLI) re-queues exactly those pages and units under
    `owner_approved(agent)`, which goes straight to Opus. Dismissing closes them without Claude.
- **Quota.** A usage limit skips that provider's other targets and never reaches a gated target.
  - The first worker to hit it records a shared pause in Redis, until the provider's own reset
    time ("try again in …") or 30 minutes by default.
  - The owner gets one red alert and push notification.
  - Every pipeline checks the pause before each unit. Deferred tasks wait exactly until the
    reset, then continue from the saved state.
- **Pause, stop and relaunch.**
  - The owner's pause stops model work between saved units on every worker.
  - `pipeline_cli relaunch` re-queues every unfinished ingest job and knowledge pass from the
    database. Finished work is skipped: pages are saved one by one, and knowledge by unit hash.
- **Knowledge v3.**
  - The prompt asks for self-contained claims, answer (not question) spans, and a `source_doubt`
    note.
  - In code, `supported_span` rejects over-reach. The claim's content words, numbers, laterality
    and negation must be in the evidence; the span is widened to adjacent sentences when that
    makes it complete.
  - Doubted claims are stored as `flagged` (with `claims.doubt`) and are never used as evidence
    until reviewed.
- **Slide text.** Symbol-font bullets ("�") become "•" at render and chunk time.

## Consequences

- Claude quota is spent only on items the owner has seen counted and approved.
- A quota hit costs one failed call, not a cascade. The owner is told when the run will resume.
- Knowledge from exam decks is held to its source: flagged source errors stay out of cards and
  questions until the owner reviews them.
- Migration `20260926_0106` adds `model_escalations`, two alert kinds, `claims.doubt` and the
  `flagged` status. It is expand-only, with a two-tenant runtime-role proof in
  `evals/checks/test_escalations_live.py`.
