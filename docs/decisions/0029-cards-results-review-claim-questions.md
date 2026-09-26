# 0029 — Cloze and image cards, exam results review with disputes, claim-based SBA generation

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0014 (cards, FSRS), ADR 0015 (assessment engine), ADR 0016 (knowledge graph),
  ADR 0018 (data rights), ADR 0024 (daily loop, calibration), ADR 0026 (worker leases),
  completion plan G9, G11, G16

**Decision.** Migration `20260926_0102` (expand-only) adds `cards.card_type`
(`basic` default, `cloze`, `image`), `cards.claim_id` (same-tenant FK, set NULL if
the claim is re-extracted away), `cards.figure_id` (same-tenant FK, the card goes
with its figure), partial unique indexes so a user has one card per claim and per
figure, widens `cards.origin` to add `claim` and `figure` (the check is swapped in
one statement for a strict superset), adds `exams.item_seconds` and
`exams.confidence` (jsonb objects, default `{}`), and creates the tenant table
`grade_disputes` (ENABLE + FORCE RLS, runtime grants, a two-tenant proof in
`evals/checks/test_cards_results_live.py`, direct erasure in the data-rights
registry, children-first in `ALL_TABLES`).
**G9 cards, no model call.** `POST /v1/study/cards/from-knowledge {kind, topic?,
source_id?, max_cards<=50}` reads the caller's usable claims — `active` (evidence span
verified verbatim at extraction, not disputed/superseded/rejected), two-source
`verified` first — or described figures without a card yet. A **cloze** card blanks
every occurrence of the claim's concept name or alias (longest first, word-bounded),
else a measurement (number and unit); a claim with neither is skipped rather than
blanked arbitrarily. The back is the term, the statement and the verbatim evidence;
the citation is the claim's source, pages and the evidence blocks (`block_refs`,
which resolve to bounding boxes in the reader). An **image** card shows the figure
through the existing signed media route (click to zoom) and asks for the key finding
and diagnosis; the caption is kept for the back, with the findings and description,
cited to the figure's page and bbox. Without a resolvable citation there is no card
(fail closed). Cards join the ordinary FSRS queue; `ReviewDeck` renders all three
types with the same keys (Space reveals, 1–4 rate). Deterministic generation was
chosen over a model call: it is instant, costs no Opus quota, and cannot invent a
blank the evidence does not support.
**G11 results review.** The exam screen measures active seconds on the item on
screen (paused while the tab is hidden) and an optional 1–3 confidence, and sends
both in the same compare-and-set autosave as the answers. The server keeps the
larger seconds per item, capped at the exam's elapsed time plus a minute, and refuses
ids outside the exam or levels outside 1–3. Keys follow the session SBA block:
A–E choose, 1–3 rate, nothing while typing or with a modifier (letters and digits
never clash). On submission every result item carries `time_seconds` and
`confidence`, SBA and written attempts store the confidence (feeding the ADR 0024
insights), and the summary gains `review`: timing totals, median, the three
slowest items, and a calibration table per confidence level (stated 0.40/0.65/0.90 vs
the share of marks earned), with bias, confidently-wrong and right-when-unsure counts.
It is recomputed whenever a pending written item is filled in; pending and failed
items stay out of calibration. It is never folded into the score and no pass
probability is computed. Each result item has a **jump to source** link (reader
deep link to the first cited page/block, highlighted for missed items).
**Grade disputes.** The exam's owner may dispute one scheme point of a graded SEQ,
image-case or viva item that did not earn full marks (`POST
/v1/exams/{id}/disputes`, one per point, audited with ids only). The owner/admin
(`org_admin`, `superadmin`) works the queue (`GET /v1/grade-disputes/review`, with
the point, grader justification, citations and the candidate's answer read live
from the stored result) and resolves it (`POST /v1/grade-disputes/{id}/resolve`):
**accept** raises the point to full marks or a given value (above the original, at
most the point's marks), recomputes item, stage and exam totals in the stored result
and marks the point `adjusted`; **reject** closes it. Both are audited with ids and
numbers only; an accept is refused if the point changed since the dispute. The
attempt row stays the append-only record of the machine grade, so item statistics
and mastery keep the original score; the exam result and the dispute row carry the
adjusted one.
**G16 claim-based SBA.** A new prompt version, `question_generate/v2` (same
`GeneratedQuestions` schema; eval fixture `evals/fixtures/assessment_v2.json`), takes a
topic's claims as numbered excerpts `C1..` (statement plus verbatim evidence, cited
to the claim's source/pages/blocks) and the concept graph's neighbours:
`differential_of` and `contrasts_with` edges first, then siblings sharing an `is_a`,
`part_of` or `classified_by` parent, all from the caller's live sources. A
neighbour with a usable claim of its own is supplied as an excerpt too, so a
distractor rationale can cite why that entity is wrong. On top of the existing
deterministic checks, code requires at least two distractors to name a supplied
neighbour (normalised name or alias); then the unchanged independent
`question_check` gate and the near-duplicate insert apply. `basis` (`auto` default,
`claims`, `chunks`) selects the path: `auto` uses claims for an SBA topic with at
least three claims and two neighbours and otherwise falls back to the unchanged
chunk path, which is pinned to `question_generate/v1` through a new `version`
argument on `run_agent` (a new prompt version can no longer silently change an old
caller). `claims` refuses with 422 when the topic cannot support it.
**Lease fix.** Reading an exam re-queued grading jobs by touching `updated_at` on
every pending or running job untouched for 10 minutes, so a page read every few
minutes kept a dead worker's run "fresh" and blocked the 15-minute takeover forever.
Now, as in the viva path, a pending job is re-queued after 10 minutes, a running job
only once it has been silent for the full takeover window (it is set back to
`pending`), and a live run is never touched.
**Trade-offs.** "Verified" means the verbatim-evidence check plus not disputed; most
personal claims have a single source, so requiring two-source agreement would leave
almost nothing to card. The admin sees the candidate's answer text in the dispute
queue (same tenant; personal mode is one person). Per-item time is client-measured
and only as honest as the browser clock, which is why it is capped server-side and
never scored. Runbooks: `docs/runbooks/study.md`, `docs/runbooks/assessment.md`;
demo: `docs/demos/m5-results-review.md`.
