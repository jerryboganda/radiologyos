# Study runbook — exam-first planner, FSRS cards, progress

- Status: current (personal-first, ADR 0011)
- Scope: `/v1/study/*`, migrations `20260926_0006` and `20260926_0010`, `packages/study/`,
  beat tasks in `apps/worker/app/study_jobs.py`
- Gates: `apps/api/tests/test_study_*.py` (local), `evals/checks/test_study_live.py` and
  `test_study_depth_live.py` (GitHub Actions `migrations` job, runtime role)
- Related: [ADR 0014](../decisions/0014-study-planner-fsrs.md), [M4 preview](m4-preview.md)

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
