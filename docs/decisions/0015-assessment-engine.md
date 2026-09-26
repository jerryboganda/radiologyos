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
