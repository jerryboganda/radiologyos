# M5 preview runbook — items, practice, and exam mode

- Status: current, non-release
- Scope: SBA items, grading, exam lifecycle, autosave and resume
- Gate: `evals/checks/test_m5_assessment.py` (slice R, S)
- Related: [M4 preview](m4-preview.md), [ADR 0006](../decisions/0006-non-release-preview-mode.md)

## Prerequisites

- Knowledge seeded for the tenant so items can be generated.
- A tenant and owner UUID.

## Normal operation

```python
from apps.api.app.preview.assessment import (
    create_exam, start_exam, autosave_exam, submit_exam, grade, list_questions,
)

exam = create_exam(state, tenant_id, owner_id)      # 5 items
start_exam(state, tenant_id, owner_id, exam.id)    # active, 600s deadline
autosave_exam(state, tenant_id, owner_id, exam.id, 1, {exam.question_ids[0]: 2})
result = submit_exam(state, tenant_id, owner_id, exam.id)
```

Over HTTP: `GET /v1/preview/questions`, `POST /v1/preview/attempts`,
`POST /v1/preview/exams`, `POST /v1/preview/exams/{id}/start`,
`POST /v1/preview/exams/{id}/autosave`, `POST /v1/preview/exams/{id}/submit`.

## Exam lifecycle

`created` → `active` → `submitted` | `timed_out`.

- Starting sets `started_at` and a deadline 600 seconds out. Starting twice
  does not extend the deadline.
- Autosave requires `active`, and the revision must be exactly
  `exam.revision + 1`. A stale or skipped revision is rejected rather than
  applied, so two clients cannot silently overwrite each other.
- Autosave validates every question id against the paper and every option
  against `range(5)`.
- Answers accumulate across revisions, so a reconnect that replays only the
  newest edit keeps the earlier ones.
- Submitting is idempotent: a second submit returns the same result and does
  not grade the paper again.
- Submitting before starting raises; an unanswered item scores zero rather than
  being credited.

## Item contract

- Five options, distinguishable, key in `range(5)`, every item cited.
- `question_view` is what the client receives and it deliberately omits `key`,
  `correct`, and `explanation`. The served view must never leak the answer.
- Explanations state that they are not clinically authoritative.

## Verification

```bash
python -m pytest -q evals/checks/test_m5_assessment.py
```

The gate asserts: items generated once and deterministically; every item well
formed and cited; the served view has exactly the six public fields and no key;
a point awarded only for the key; unanswered scored zero; out-of-range options
and unknown questions rejected; grading audited; the full exam lifecycle;
double-start not extending the deadline; five cited items per paper;
autosave accumulation; a disconnect/resume preserving earlier answers; stale
revisions rejected; out-of-paper questions and bad options rejected; autosave
refused after submission; scores in bounds with a full breakdown; resubmission
not double-crediting; owner and tenant scoping; and exam audit ordering.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ValueError: exam has not started` | submitting a `created` exam | `start_exam` first |
| `ValueError: exam is not active` | autosave or submit after submission | exam is final |
| `ValueError: stale exam revision` | revision skipped or replayed | resync and send `exam.revision + 1` |
| `ValueError: invalid exam answer` | question not on the paper, or option outside 0–4 | validate before sending |
| `LookupError: exam not found` | wrong owner or wrong tenant | exams are owner-scoped |

## Rollback

There is no exam deletion. Resetting preview state clears exams, attempts, and
items. Because submissions are terminal, a mistaken submit cannot be undone in
place; that is intentional so scores stay auditable.

## Escalation

If `question_view` ever returns `key`, `correct`, or `explanation`, every
generated item is compromised. Treat it as a security incident and invalidate
the affected items.

## Known limitations

- One item kind only (`sba`). No SEQ, image-case, or viva items; `viva` is
  explicitly omitted from Today.
- Item ids are content-addressed, so two tenants share the same UUIDs. Tenant
  separation comes from the scoping on every read, not from the id.
- The 600-second deadline is fixed and not configurable.
- No item-quality metric beyond "well formed and cited". There is no
  discrimination index, no distractor analysis, and no versioned prompt
  registry behind the generator.
