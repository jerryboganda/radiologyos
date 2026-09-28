# 0041 — The red review list shows the evidence and records the owner's verdict

- Status: accepted (owner, 2026-09-28: "make sure I can review all the red review list
  properly… the reference file name and page number… highlighted… so I can just review it
  and give my opinion… and then we can further save it down the road in the data")
- Amends: ADR 0038 (red review list), ADR 0037 (collect & ask)

## Decision

- **Evidence with every item.** Each red item shows the file name, the title, and the exact
  page or page range, plus the evidence for its kind:
  - a page shows its own text layer beside what the model read;
  - a figure shows its reading, findings and source quote, with the page image;
  - a note section shows its full text, with every extracted statement's evidence
    highlighted.
- **Flagged facts** carry their section's text around the evidence.
- **Endpoints:**
  - `GET /summary` groups the list by file;
  - `GET ?source_id=` returns one file's items;
  - `GET /export.csv` downloads everything.
- **The owner's verdict.** For each item the owner chooses one of these and may add a note:
  - `correct`: keep it as it is;
  - `needs_fix`: redo or correct it;
  - `remove`: take it out.
- **Where decisions are stored.**
  - Item verdicts and notes are stored on `model_escalations` (migration `20260928_0108`,
    expand-only).
  - A decision on a fact, and its note, is stored on `claims`.
  - The owner can change a decision later.
  - The follow-up work reads these decisions.
- **Upkeep.**
  - `pipeline_cli red-list --prune` removes items fixed since they were listed: a failed
    page that has since been read, or a failed or since-replaced note section. It never
    touches an item the owner has judged.
  - `pipeline_cli redo-approved` runs approved note sections whose knowledge pass had
    already finished, so they had never been redone on Opus.
  - Approving now reopens those passes as well.
- **Keeping the best answer.** When Opus, the last target, errors after Luna and Sol gave
  valid answers below the bar, the best answer is kept and listed (`kept_best_after_failure`).
  Before, the item failed and nothing was stored.

## Consequences

- The owner can judge each item on one screen and record why.
- Every later fix follows the owner's own words.
- Evidence is the owner's own content, shown only to the owner. It is never logged.
