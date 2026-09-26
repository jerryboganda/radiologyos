# Study runbook — exam-first planner, FSRS cards, progress

- Status: current (personal-first, ADR 0011)
- Scope: `/v1/study/*`, migration `20260926_0006`, `packages/study/`
- Gates: `apps/api/tests/test_study_*.py` (local), `evals/checks/test_study_live.py`
  (GitHub Actions `migrations` job, runtime role)
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
   counts, and per-system mastery bands. It never shows a pass probability.

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
- Weights: all systems are weighted equally until the owner approves past-paper
  weights in `packages/curriculum/` (stop-and-ask rule).
