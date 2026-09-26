# Study runbook — exam-first planner, FSRS cards, progress

- Status: current (personal-first, ADR 0011)
- Scope: `/v1/study/*`, migrations `20260926_0006`, `20260926_0010` and `20260926_0016`,
  `packages/study/`, beat tasks in `apps/worker/app/study_jobs.py`
- Gates: `apps/api/tests/test_study_*.py` (local), `evals/checks/test_study_live.py`,
  `test_study_depth_live.py` and `test_study_sessions_live.py` (GitHub Actions
  `migrations` job, runtime role)
- Related: [ADR 0014](../decisions/0014-study-planner-fsrs.md),
  [ADR 0024](../decisions/0024-daily-study-loop.md), M4 gate `evals/checks/test_m4_planner.py`,
  [five-minute demo](../demos/m4-study-loop.md)

## Onboarding

The exam date comes first. Until `PUT /v1/study/profile` succeeds, `GET /today`
and `GET /progress` answer 409 and `GET /profile` answers 404.

```json
PUT /v1/study/profile
{"exam_date": "2027-02-15", "exam_targets": ["fcps2_theory", "fcps2_toacs", "imm", "frcr"],
 "daily_minutes": 90, "weekday_minutes": 75, "weekend_minutes": 150,
 "timezone": "Asia/Karachi", "reminder": {"enabled": true, "time": "06:30"}}
```

The date must be after today in the profile's time zone. Saving a profile deletes
today's and future cached plans so the next `GET /today` reflects it.

## Daily loop

1. `GET /v1/study/today` returns the cached plan for the local day, or builds one
   (`?refresh=true` rebuilds). Blocks: `review`, `learn`, `test`, `viva`; their
   minutes always sum to the day's minutes.
2. `GET /v1/study/cards/due?limit=50` returns due review cards first, then new cards
   up to the 25-per-day cap (none in the taper phase).
3. `POST /v1/study/cards/{id}/review {"rating": 1..4}` (Again, Hard, Good, Easy)
   reschedules with FSRS-5 and appends a `card_reviews` row.
4. `GET /v1/study/progress` shows days remaining, phase, retention target, review
   counts, the weight basis, and per-system mastery bands (accuracy blends question
   attempts with card reviews; coverage counts cards and active questions). It never
   shows a pass probability.

## Today session runner (ADR 0024)

The Today page runs the day as one resumable session. `GET /v1/study/sessions/today`
builds it the first time it is asked for on a local day (409 without a profile) and
returns the stored one afterwards, on any device.

| Step | Content | Done when |
| --- | --- | --- |
| `review` | Due cards (oldest first), then today's new cards within the 25/day cap | All rated, or marked done |
| `learn` | Cited passages and described figures for the plan's top topic | Marked done (passages then count as studied) |
| `test` | Timed SBA block (plan-sized, max 20, 1.5 min each; re-tests first) | Every item answered, or marked done |
| `viva` | One open question graded by `seq_grade`, else a cited self-review prompt | Answered, or marked done |

- `POST /v1/study/sessions/{id}/steps/{n}/start` starts a step (the SBA clock starts
  here; answers are refused 30 s after the deadline).
- `POST .../steps/{n}/answer` takes `{"question_id", "selected_option": 0..4,
  "confidence": 1..3}` for SBA or `{"answer_text"}` for the viva. The first answer
  stands; repeats change nothing.
- `POST .../steps/{n}/complete[?skip=true]` marks a step done or skipped.
- `POST /v1/study/sessions/{id}/complete` skips what is left, freezes the summary
  (reviews, SBA results, minutes, weighted coverage) and deletes tomorrow's cached plan
  so the nightly replan rebuilds it.

A step with nothing citable (no due cards, no mapped passages for the topic, no SBA
questions, nothing for a viva) is left out. A graded viva appears as a one-item
practice exam in `/exams` (`config.kind = session_viva`); its result fills in when the
worker has graded it (the grading worker and a model token must be running).

## Weakness loop

- A wrong SBA answer (practice attempt, Today session, or submitted exam) creates a
  `weakness` card from that question, citing the question's chunk, due in one day. A
  later miss on the same question pulls the same card forward instead of adding one.
  It also opens a `weakness_events` re-test due within two days. The next session's
  SBA block serves open re-tests first; any answer to that question closes them.
- A card rated Again relearns in 10 minutes (FSRS) and queues a re-test of an active
  SBA question that cites the same chunk, if there is one.
- Events are unique per attempt or review id: replays and retries add nothing.
- A question whose chunk has no accepted curriculum mapping gives a card coded
  `UNMAPPED` (reviewable; not counted in mastery). Map the source to fix it.

## Progress insights

`GET /v1/study/insights` (409 without a profile) feeds the Progress page:

- **Coverage heatmap**: rows are curriculum systems, cells their child topics (deeper
  codes roll up; a system with no topics has one cell). A cell is the share of mapped
  passages studied (card reviewed, question answered, or read in a finished learn
  step), with accuracy when there are attempts. A table view is the accessible
  fallback.
- **Days-remaining projection**: pace comes from completed sessions over 28 days
  (their frozen weighted coverage and minutes). With fewer than 3 days of history it
  says "insufficient history". It shows projected coverage on exam day and the
  minutes per day needed for 90 % weighted coverage 30 days before the exam.
- **Calibration**: accuracy by self-rated confidence (low, medium, high read as 40, 65
  and 90 %). The bias and confidently-wrong count appear after 10 rated answers.
  Calibration is never part of mastery.

None of these is a pass probability.

## Keyboard shortcuts

| Where | Keys |
| --- | --- |
| Card review | Space reveals · 1 Again · 2 Hard · 3 Good · 4 Easy |
| Today SBA block | A–E choose · 1–3 confidence · Enter submit / next |
| Exams | A–E choose |

Shortcuts are off while typing in a text field or with Ctrl, Alt or Cmd held.

## Weights

The planner uses the owner's **approved** past-paper weights
(`POST /v1/knowledge/topic-weights/approve`) for the profile's exam targets, else the
approved `all` aggregate, else equal weights. `/today` and `/progress` report
`weight_policy` (`past_paper_approved` | `equal_unvalidated`) and `weight_targets`.
Approving or re-approving weights takes effect on the next plan build; use
`/today?refresh=true` to rebuild today's plan at once. A recomputed weight loses its
approval (ADR 0016) and the planner falls back until it is approved again.

## Baseline test

`POST /v1/study/baseline` builds a timed SBA exam of up to 20 active, checked
questions spread round-robin across systems (1.5 min per question) and returns
`exam_id`; the user takes it at `/exams/{exam_id}` (Today → "Take baseline test").
An open baseline is returned again (200) instead of creating a second one. 409 means
fewer than 8 checked SBA questions are linked to a curriculum system: generate SBA
questions from library sources whose chunks have curriculum mappings (knowledge
extraction) or cards. `GET /v1/study/baseline` shows the latest one; once its exam is
submitted (or expires) the per-system results are frozen on `baseline_tests`. The
graded attempts feed mastery like any other attempt.

## Weekly report and nightly replan

Celery beat (worker must run with `-B` or a beat process) schedules:

- `radbrain.weekly_reports` hourly: `app.weekly_reports_due(now)` returns users whose
  local time is past Monday 06:00 and who have no report for last week; the report
  is computed in code and upserted into `weekly_reports`. Read it with
  `GET /v1/study/reports/latest` (404 until the first one) or on `/progress`.
- `radbrain.nightly_replan` every 30 minutes: `app.study_replans_due(now, version)`
  returns users whose local time is past 22:00 and who have no plan for tomorrow at
  the current `PLANNER_VERSION`; tomorrow's plan is built as of local midnight.

Both resolvers return `(tenant_id, user_id)` only and skip a profile whose time zone
PostgreSQL does not know. Logs carry counts and error class names only. To rebuild a
report by hand, run `reports.store_weekly_report(repo, user_id, now, week_start)`
in a tenant-scoped session; it is idempotent per user and week.

## Cards

- Manual: `POST /v1/study/cards {chunk_id, curriculum_code, topic, front, back}`.
  The chunk must belong to the caller (from `POST /v1/library/search` hits);
  the server builds the citation. Codes are the curriculum system codes, e.g. `CHEST`.
- Generated: `POST /v1/study/cards/generate {"source_id": ...}` or
  `{"chunk_ids": [...]}` (up to 8 chunks, `max_cards` 1–20). It runs the
  `card_generate` agent synchronously through the Claude Code CLI; 503 means the
  CLI is missing or the usage window is exhausted (retry later), 502 means the
  output failed validation. `rejected` counts cards dropped by the guardrails.
- Cloze and image (ADR 0029, migration `20260926_0102`):
  `POST /v1/study/cards/from-knowledge {"kind": "cloze"|"image", "topic"?, "source_id"?,
  "max_cards"<=50}`, or **Cards from your knowledge** on Today. No model is called.
  Cloze cards come from `active` claims (verbatim evidence, not disputed), two-source
  `verified` first, with the concept name/alias (else a measurement) blanked; image cards
  come from figures with a description. `skipped` counts candidates with nothing
  citable to blank. Each claim and figure gets at most one card per user, so a rerun
  only picks up new claims and figures. The card's code is the concept's (or the
  chunk's accepted mapping's) system, else `UNMAPPED`.
- Reviewing: cloze blanks are underlined and filled in on reveal; image cards load
  through `/media/figures/{id}` (click the image to zoom). Space reveals, 1–4 rate.
- If image cards show "image unavailable", the figure crop has no stored image yet
  (re-run the vision pass for that source); the card still cites the page.

## Troubleshooting

- 409 on `/today`: no profile; complete onboarding.
- Plan looks stale after a code change: the cache is keyed by `plan_version`;
  otherwise call `/today?refresh=true`.
- A review answers 422: the rating is outside 1–4, or the clock moved backwards
  relative to the card's last review.
- Weights still equal: no approved system-level weights exist for the profile's exam
  targets (or `all`); approve them on the knowledge page.
- No weekly report on Monday: check beat is running, the profile's time zone is a
  valid IANA name, and the profile existed before the week began.
- Baseline 409: see "Baseline test" above.
- Today shows "Nothing to run yet": no due cards, no passages mapped to the top topic, no
  active SBA questions. Generate cards or questions, or map sources, then reload
  tomorrow (today's session is fixed once built).
- Viva result stays "being marked": the grading worker is down or the model token is
  missing; the job is re-queued when `/exams/{id}` is read after 10 minutes.
- Projection says "insufficient history": finish sessions on at least two days, three
  or more days apart.
