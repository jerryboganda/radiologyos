# M2 preview runbook — knowledge extraction and the graph

- Status: current, non-release
- Scope: synthetic extraction, entity resolution, conflicts, editor authority
- Gate: `evals/checks/test_m2_knowledge.py` (slice I, J, K, L)
- Related: [M1 preview](m1-preview.md), [ADR 0006](../decisions/0006-non-release-preview-mode.md)

## Prerequisites

- `PREVIEW_ENABLED=true` in a local or test environment. Never on the public host.
- A tenant and an owner UUID. Every call takes `tenant_id` and `owner_id`; the
  tenant is never inferred from a request body.

## Normal operation

```python
from apps.api.app.preview.knowledge import ensure_knowledge, extract_source

# Seed the synthetic knowledge fixture (idempotent, once per tenant).
ensure_knowledge(state, tenant_id, owner_id)

# Extract one cited claim per chunk from a ready source.
claims = extract_source(state, tenant_id, owner_id, source_id)
```

Over HTTP: `GET /v1/preview/concepts`, `/claims`, `/conflicts`,
`POST /v1/preview/sources/{id}/extract`.

## What is deliberately not implemented

- Entity resolution merges two sources into one concept. `ensure_knowledge`
  seeds exactly one concept and returns early if the tenant already has any, so
  repeated seeding cannot fan out. Real resolution is not attempted.
- Curriculum mapping is absent. `weight_policy` is `equal_synthetic_preview`
  and no exam weight is inferred.
- The editor queue reports `pending_mappings = 0` and `pending_questions = 0`.
  There is no mapping workflow behind those numbers.

## Verification

```bash
python -m pytest -q evals/checks/test_m2_knowledge.py
```

The gate asserts, among others: one cited claim per chunk, extraction
idempotency, refusal for a foreign owner / quarantined source / other tenant,
concept-name uniqueness, concept-to-claim referential integrity, cross-tenant
graph disjointness, editor/admin role denial (403), an invalid role rejected
outright (400), a blank role falling back to unprivileged, a closed resolution
vocabulary, and a cross-tenant conflict resolve returning 404 rather than
succeeding.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `LookupError: source not found` | wrong owner, wrong tenant, or the source is `quarantined` | check `source.owner_id` and `source.status` |
| Duplicate claims after re-extracting | not possible: extraction short-circuits on an existing claim for that source | if seen, the guard in `extract_source` was bypassed |
| 400 `invalid local role` | role outside `student, editor, org_admin, superadmin` | use a declared role |
| 403 `insufficient role` | valid role without the required privilege | editor/admin endpoints need `editor`+ |

## Rollback

Extraction only appends claims. To undo, delete the source: `delete_source`
purges the claims derived from it along with its chunks, pages, blocks,
figures, and jobs, and releases its idempotency key.

## Escalation

A claim that resolves to another tenant's source is a containment failure, not
a bug in the caller. Stop, capture the request ids from the API logs, and treat
it as a security incident.

## Known limitations

- Knowledge is a single seeded fixture plus whatever extraction produces.
  There is no real ontology, no curriculum, and no conflict detection logic —
  the seeded conflict exists so the editor path is exercisable.
- `PreviewClaim.verification` is set to `verified` by the fixture. No
  verification workflow backs that value.
