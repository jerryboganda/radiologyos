# 0035 — ChatGPT via Codex and the owner's model rules

- Status: accepted (owner decision, 2026-09-26; the owner called it mission critical)
- Supersedes: ADR 0033 (Sonnet page reading) and, for bulk work, ADR 0010's single-provider routing
- Amends: ADR 0027 (per-agent targets), ADR 0021 (quota efforts)

## Why

The first library pass ran bulk work on the owner's Claude Max subscription:
- page reading on Sonnet 5 at high effort;
- figure descriptions on Opus 5.5 at high effort.

The owner has a much larger ChatGPT Business quota, and wants Claude kept for
the work they do directly.

## Decision

The concrete names live only in `packages/models/models.yaml`.

- **Pages and figures** (`page_parse`, `image_case`), in this order:
  1. GPT-6 Luna at high effort.
  2. GPT-6 Sol at high effort.
  3. Claude Opus 5.5 at high effort, which carries `requires_owner_approval`.
- **The approval gate.** The gateway never calls an approval-gated target unless the host sets
  `BULK_CLAUDE_FALLBACK_APPROVED=true`. Otherwise it raises `OwnerApprovalRequired`, a usage-limit
  pause: the job waits and nothing is sent.
- **Knowledge** (`knowledge_extract`, `topic_classify`, `paper_topics`, `concept_synthesis`,
  `concept_resolver`, `claim_conflict`): GPT-6 Luna at max effort on the Fast tier
  (`service_tier="priority"`).
- **Everything the owner uses directly** (tutor, web research, grounding judge, memory, question
  generation and checking, grading, cards, viva, staged cases): Claude Opus 5.5 at medium effort.
  Opus 5.5 at high is never used except as the approved last resort above.
- **Free first.** Firecrawl's pdf-inspector decides which pages have a usable text layer, and
  those pages need no model call.
  - This now also covers PPTX and DOCX: the check runs on the same LibreOffice PDF the pages are
    rendered from.
  - The 347 standalone images always need vision.

## How ChatGPT is reached

The Codex CLI (`@openai/codex`, pinned 0.157.1, copied into the Python image as its static
binary) runs `codex exec` with these settings:
- read-only sandbox, approvals off, ephemeral;
- the chosen model, reasoning effort and service tier;
- the agent's JSON Schema as `--output-schema`, with `additionalProperties: false` added
  everywhere;
- page images passed as `-i`;
- the prompt on stdin, never in argv.

The owner signed in once with `codex login --device-auth`.
- The OAuth sign-in is stored in `/opt/radiologyos/codex/auth.json` on the host: root-only,
  mounted as `CODEX_HOME` into the worker and the API, never in git.
- Before building on it, the model catalog (`codex debug models`) was checked to confirm
  `gpt-6-luna` and `gpt-6-sol`, their efforts, image input, and the Fast tier.

## Consequences

- The Claude quota is used only for interactive work, plus bulk work the owner explicitly
  approves.
- A bulk job that cannot run on Luna or Sol pauses instead of spending Claude quota. The owner
  can see it and decide.
- The knowledge agents have no fallback. If Luna is unavailable, those units wait.
- Every bulk run is preceded by a small test run whose models and usage are shown to the owner.
