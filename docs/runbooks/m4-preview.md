# M4 preview runbook — planner, Today, and scheduling

- Status: current, non-release
- Scope: onboarding, phased plan, Today runner, FSRS-style cards, mastery
- Gate: `evals/checks/test_m4_planner.py` (slice P, Q)
- Related: [M6 preview operations](m6-preview-operations.md), [ADR 0006](../decisions/0006-non-release-preview-mode.md)

## Prerequisites

- A tenant and owner with knowledge seeded, so cards can be created.
- An exam date, hours per week, and session length. All three are inputs; none
  is inferred.

## Normal operation

```python
from datetime import date, timedelta
from apps.api.app.preview.learning import create_plan, today, review_card, mastery

plan = create_plan(state, tenant_id, owner_id,
                   exam_date=date.today() + timedelta(days=90),
                   hours_per_week=10, session_minutes=60)
session = today(state, tenant_id, owner_id)      # requires a plan
review_card(state, tenant_id, owner_id, card_id, rating=4)
mastery(state, tenant_id, owner_id)
```

Over HTTP: `POST /v1/preview/plan`, `GET /v1/preview/plan/today`,
`GET /v1/preview/cards/due`, `POST /v1/preview/cards/{id}/review`,
`GET /v1/preview/mastery`.

## Phases

`phase_for(days_remaining)` is a pure function with exact boundaries:

| Days remaining | Phase |
| --- | --- |
| `> 180` | `coverage` |
| `90–180` | `coverage_consolidation` |
| `30–89` | `consolidation` |
| `7–29` | `exam_mode` |
| `< 7` (incl. 0) | `taper` |

## Scheduling

`review_card` rating: `1` lapse (10 min, stability ×0.5, difficulty +0.8),
`2` hard (1 day, ×0.8), `3` good (stability ×1.5), `4` easy (×2.0). Ratings
outside `1..4` are rejected. Stability never falls below 1.0 and difficulty
stays within `[1.0, 10.0]`.

A review publishes a **new** card. It never mutates the stored instance, so a
caller holding a reference cannot be surprised by an in-place edit.

## Verification

```bash
python -m pytest -q evals/checks/test_m4_planner.py
```

The gate asserts: Today refuses before onboarding; the onboarding → Today loop
closes; block durations sum exactly to the configured session; `viva` is
omitted rather than faked; every phase boundary exactly; a past exam date
clamps to zero days; the planner never claims to be a blueprint or a pass
prediction; priorities are ordered and unique; replan bumps the version and
keeps the exam date; plan events are audited in order; cards are not duplicated
by replanning; a good review defers, a lapse shrinks stability and schedules a
ten-minute retry; ratings outside the range are rejected; review refuses a
foreign owner and an unknown card; the due queue drains; and learning state is
per-owner and per-tenant.

Note that phase boundaries are asserted through `phase_for` directly. Asserting
them through `create_plan` makes the test depend on the machine timezone,
because the plan derives `days_remaining` from the UTC clock.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ValueError: onboarding required` | `today` or `replan` before `create_plan` | onboard first |
| Today block durations do not add up | `session_minutes` under 5, so the 1-minute floors collide | use a realistic session length |
| `ValueError: rating must be between 1 and 4` | rating outside 1–4 | use the declared scale |
| `LookupError: card not found` | wrong owner, or a card from another tenant | cards are owner-scoped |
| `mastery` looks identical per node | expected: v1 reports one owner-level aggregate on every node | documented below |

## Rollback

Plans are replaced wholesale by `create_plan` or `replan`. Cards are owned by
the learner and are not deleted by replanning. There is no plan deletion
endpoint; resetting preview state clears both.

## Escalation

If `weight_policy` is ever anything other than `equal_synthetic_preview`, or
`notice` stops carrying the blueprint disclaimer, a curriculum decision has
leaked into the code. Curriculum weights are a human decision with an ADR; stop
and revert.

## Known limitations

- No baseline test: `baseline_status` is always `not_implemented`.
- `mastery` returns `synthetic_proxy_v1`, an owner-level aggregate replicated
  onto every curriculum node. It is not a per-node model and must not be read
  as one.
- Cards are seeded from a fixed synthetic node list, not from the tenant's
  actual extracted knowledge.
- No reminders, no nightly replan job, no weekly report, and no PWA
  implementation.
