# 0014 — Persistent exam-first planner and in-house FSRS-5 scheduler

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0011 (personal-first), spec section 7

The in-memory preview planner (`apps/api/app/preview/learning.py`) is replaced for
real use by a persistent study engine. Migration `20260926_0006` adds
`study_profiles`, `cards`, `card_reviews`, and `study_plans`, each with ENABLE +
FORCE RLS and a two-tenant runtime-role proof (`evals/checks/test_study_live.py`);
`card_reviews` is append-only for the runtime role. The rules are pure code in
`packages/study/`: phases by days remaining, priority `p = w(1-m)(1+0.5c)d`, the
spec's session mix sized to the day's minutes (block minutes always sum to the
available minutes; review time shrinks to what due cards need or borrows up to half
of the learning time), a 25-new-card daily cap, and mastery `m = 0.5a + 0.3r + 0.2k`
with bands and **no pass probability**. **FSRS-5 is implemented in-house**
(`packages/study/fsrs.py`, published default parameters, desired retention 0.90
raised to 0.93 in the last 30 days, no learning steps, 10-minute relearn) instead of
adding `py-fsrs`, so no new dependency is needed; per-user parameter optimisation
after 400 reviews remains future work and `card_reviews` keeps what it needs.
Interim choices, until the knowledge and assessment layers are persistent: exam
weights are equal (`weight_policy: equal_unvalidated`) because the curriculum pack
has none and weights need owner approval; accuracy `a` uses card reviews (rating
≥ 2 counts as correct) in place of question attempts; coverage `k` is the share of
a system's cards reviewed at least once; `c` is a lapse in the last 7 days. Every
card must cite a chunk the user owns: the server builds the citation (source, pages,
blocks) from that chunk and the database refuses a card without one; deleting a
source deletes its cards and reviews, as it already deletes its pages and chunks.
The `card_generate` agent (route `extract`, effort high) only sees the caller's
chunks, and a card is kept only if it cites a supplied chunk, uses a known system
code, and quotes verbatim evidence from that chunk.

**Amendment (study depth, migration `20260926_0010`).** The interim choices above
are replaced by real signals now that the knowledge and assessment layers are
persistent. *Weights:* the planner's `w` comes from the owner's **approved**
system-level `topic_weights` (ADR 0016) for the profile's exam targets
(`packages/study/weights.py`): per target, a system left unapproved gets that
target's smallest approved weight, each target is normalised, targets are
averaged, and the result is normalised to sum to 1; with no approved rows for any
profile target the approved `all` aggregate is used, else equal weights. The basis
is exposed as `weight_policy` (`past_paper_approved` | `equal_unvalidated`) and
`weight_targets` on `/v1/study/today` and `/v1/study/progress`; `PLANNER_VERSION`
is 2 so cached plans rebuild. *Mastery:* accuracy `a` blends graded question
`attempts` (fractional score, weight 2) with card reviews (rating ≥ 2, weight 1),
both with the 14-day half-life; coverage `k` is the share of a system's cards and
active questions touched at least once. A question's system is resolved from the
chunks it cites (accepted `curriculum_mappings` and the user's cards on those
chunks vote; unmapped questions do not count). *Baseline:* `POST /v1/study/baseline`
picks up to 20 active, checked SBA questions round-robin across systems (≥ 8
required, else 409) and creates an ordinary server-timed assessment exam
(1.5 min/item) plus a `baseline_tests` row; submitting the exam writes `attempts`,
which feed mastery, and the per-system summary is frozen when the baseline is next
read. *Weekly report and nightly replan:* two Celery beat tasks ask narrow
SECURITY DEFINER resolvers (`app.weekly_reports_due`, `app.study_replans_due`,
ids only, unknown time zones skipped) which users are due, then work under that
tenant's RLS context: a code-computed report (minutes estimated from review and
attempt timestamps with a 5-minute idle cap, reviews, true retention vs target,
weakest systems, next-week focus, notes) is upserted into `weekly_reports` once
per user and local week from Monday 06:00, and tomorrow's plan is built after
22:00 local, idempotent per user, date, and plan version. No model is called and
no pass probability is computed. Both new tables have ENABLE+FORCE RLS and a
two-tenant runtime-role proof in `evals/checks/test_study_depth_live.py`.
