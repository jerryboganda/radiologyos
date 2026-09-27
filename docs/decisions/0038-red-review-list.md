# 0038 — The owner's red review list

- Status: accepted (owner, 2026-09-27; a standing project rule: "make sure I don't have to remind you")
- Amends: ADR 0037 (collect & ask), ADR 0027 (quality gates)

## Why

The owner approved Claude Opus 5.5 high for items GPT-6 Luna and Sol could not answer.
- Of Opus's first 94 answers, 35 were still below the quality bar.
- The gateway kept each one, because no stronger model was left, and recorded it only as an
  anonymous ledger outcome (`gate_kept_last`).
- The owner could not see which pages, figures, or notes those were.

## Decision

- **What goes on the list.** The gateway sets `ModelResult.shortfall` when it keeps the last
  target's answer although the quality gate rejects it.
  - The vision pass (pages, figures) and the knowledge pass record every such item with
    `escalations.flag_review`, as a `model_escalations` row with status `review` and the gate's
    reason code.
  - Items every model failed (`all_models_failed`) are recorded the same way.
  - Verified output is still stored. The flag says "check this", not "discard this".
- **Where the owner sees it.** `GET /v1/library/red-list` lists these items, and the web page
  shows them in red with a danger sign.
  - Each item links to its source and page.
  - Each can be marked reviewed (`POST .../{id}/reviewed`, status `reviewed`).
- **Flagged facts are on the same page.** These are facts the extractor flagged as
  contradicting standard teaching (`claims.status = 'flagged'`). The owner keeps each as written
  or rejects it.
- **It is a project rule.** It is hard rule 11 in `CLAUDE.md`: any new AI step or quality gate
  must feed this list.
- **Work before the list existed.** `pipeline_cli red-list` backfills it:
  - every item Opus redid before this change, since its per-item outcome was not stored, so all
    of them are listed;
  - every page and knowledge unit all models failed.
- Migration `20260927_0107` widens the status CHECK. It is expand-only.

## Consequences

Nothing below the bar is kept silently: the owner sees every such item, where it is, and why it
fell short.
