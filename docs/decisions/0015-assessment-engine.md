# 0015 — Persistent assessment engine: cited generation, independent check, server-timed exams

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0010 (model routes), ADR 0011 (personal-first), ADR 0012 (library)

Migration `20260926_0007` adds `questions`, `exams`, and `attempts` (ENABLE+FORCE
RLS, two-tenant runtime-role proof in `evals/checks/test_assessment_live.py`;
attempts are append-only for the runtime role) plus an additive unique index on
`figures (tenant_id, id)` so image questions reference figures within one
tenant. Questions are generated only from numbered excerpts of the caller's own
library (hybrid search for a topic, or a chunk sample for chosen sources, capped
at 8 excerpts / 24k chars, plus one described figure for image cases and vivas)
by three versioned agents: `question_generate` (`reason`, high effort) writes
SBA, SEQ, TOACS image-case, or viva items for FCPS-II theory, FCPS-II TOACS, IMM,
or FRCR; deterministic code checks then reject any item that cites an excerpt
that was not supplied, lacks five distinct options, uses "all/none of the
above", repeats the key in the stem, exceeds 120 stem words, or lacks a cited
marking scheme; `question_check` (`classify`, high effort) independently checks
single-best-answer, key support, cueing, and distractor plausibility, and only a
pass makes an item `active` (fails and checker errors stay `draft`). Free-text
answers are graded by `seq_grade` (`reason`, high effort), then normalised in
code against the frozen marking scheme: one result per scheme point, marks
clamped, and no credit outside the scheme. SBA grading is exact match in code.
Exams hold SBA items only in this version; the server fixes the deadline at
creation, autosave is compare-and-set on `revision`, autosave after the deadline
is refused, an expired exam is graded from its last saved answers when it is next
read or submitted, and submission is idempotent. Answer keys, explanations, and
citations leave the API only in an attempt result or a submitted exam result,
and single-question attempts are refused while the question sits in an open
exam, which closes the preview's "attempts as answer oracle" hole. Generation
and grading run synchronously in the request with the database transaction
committed during the model call; bulk generation should move to a worker job.

## Addendum (2026-09-26): assessment depth — migration `20260926_0011`

Migration `20260926_0011` (after `20260926_0010`) is expand-only: nullable
`questions.stem_norm`, `embedding vector(1024)` (HNSW cosine index),
`embed_model`, `status_reason`, `status_changed_at`; `exams.text_answers`
(jsonb, default `{}`); and two tenant tables, `item_stats` and `grading_jobs`,
with ENABLE+FORCE RLS and a two-tenant runtime-role proof in
`evals/checks/test_assessment_depth_live.py`. Exams now mix SBA with SEQ, image
case, and viva items (`ExamCreate.types`, default `["sba"]`, which supersedes
"SBA items only" above); written answers autosave in the same compare-and-set
revision as options. On submit, SBA items and blank written items are graded at
once, and each answered written item gets one `grading_jobs` row keyed by
(tenant, exam, question, grading version). The API enqueues
`radbrain.grade_exam_item` only after commit; the worker grades with
`seq_grade` outside any transaction, then one transaction stores the outcome,
fills the item into the stored result (per-item `status` pending/graded/failed;
the summary counts pending as zero and reports `grading`), and appends the
attempt. A duplicate task is a no-op while another run holds the job (a run
untouched for 15 minutes is taken over); a usage-limit or missing-runtime pause
re-queues after 30 minutes (failed after 48 runs), a model error retries after
60 s (failed after 3 errors), and reading the exam re-queues jobs untouched for
10 minutes. Item statistics follow spec section 8 step 7: facility is the mean
score fraction, discrimination is the item-rest point-biserial correlation over
exam attempts, and after 50 attempts an active item retires (`status_reason =
stats:<code>`, audited) when facility leaves 0.25–0.85 or, once 20 exam
responses exist, discrimination is below 0.20. Statistics are recomputed per
owner inside that owner's tenant context — by the worker when an exam finishes
grading and on demand via `POST /v1/questions/stats/recompute`; a nightly
cross-tenant beat was rejected because it needs a cross-tenant resolver that
widens RLS. Generation rejects near-duplicates of the owner's bank before
insert, one item at a time so a batch also dedupes itself: stem-embedding cosine
≥ 0.92 when Voyage is configured, otherwise (or when embedding fails) `pg_trgm`
`similarity()` ≥ 0.9 over normalised stems; rejects return `duplicate_of` and
`similarity`. The owner's review queue (`GET /v1/questions/review`, `POST
/v1/questions/{id}/review`) shows drafts in full with checker reasons; approve
activates a draft only when the deterministic checks pass and every cited
source page and figure still exists in a live source (chunk ids are not used
because re-chunking replaces them); reject retires it; edit changes wording
only (citations are not editable) and re-runs the checks. Every review action
is audited with ids and field names only. No new model agent, prompt, or
dependency was added.
