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
