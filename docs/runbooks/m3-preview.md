# M3 preview runbook — retrieval, grounding, and tutor threads

- Status: current, non-release
- Scope: retrieval, citations, the ungrounded guard, thread memory
- Gate: `evals/checks/test_m3_tutor.py` (slice M, N, O)
- Related: [M1 preview](m1-preview.md), [ADR 0006](../decisions/0006-non-release-preview-mode.md)

## Prerequisites

- At least one ingested, non-quarantined source for the tenant.
- `PREVIEW_ENABLED=true` locally. Never on the public host.

## Normal operation

```python
from apps.api.app.preview.tutor import ask

result = ask(state, tenant_id, owner_id, "costophrenic angle")
result["answer"]      # assembled from retrieved chunk text
result["citations"]   # source_id, page_no, block_id, bbox
result["grounding"]   # always "mock_lexical_preview"
```

Over HTTP: `POST /v1/preview/tutor/ask`, `POST /v1/preview/search`.

## The grounding contract

- Retrieval is lexical token overlap over tenant-scoped chunks, top 4, figures
  top 2. There is no embedding stage, no hybrid fusion, and no reranker; the
  `embed_index` ingest step stays `skipped` with `provider_gate_blocked`.
- Every returned sentence carries a `[1]` marker and a matching entry in
  `citations`.
- When nothing matches, the answer is exactly
  `I do not have a grounded answer in the selected sources.` and `citations`
  is empty. There is no partial or hedged answer.
- `grounding` is always `mock_lexical_preview`. The response never claims a
  model-backed route.

## Verification

```bash
python -m pytest -q evals/checks/test_m3_tutor.py
```

The gate asserts: a citation marker on every sentence; every citation resolving
to a real page of a real tenant-scoped source; top-k bounded; a latency
ceiling; the declared grounding mode; refusal with no citations for an
unsupported or empty-tenant query; figure captions with tenant-prefixed object
keys; answer text drawn only from cited evidence; thread recording and its
40-message bound; per-owner and per-tenant thread separation; and that neither
tenant can ground on the other's phrases.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Always the refusal sentence | nothing matched, or the tenant has no ready source | confirm the source is `ready` and not `quarantined` |
| Refusal for a term you can see in a source | it exists in a *different* tenant | expected; cross-tenant grounding is closed |
| `grounded_state` helper returns nothing | the harness fixture is broken | run the fixture guard test in the gate |
| Latency above the budget | unbounded fan-out over many sources | top-k is fixed at 4; check for a changed limit |

## Rollback

`ask` only appends to the owner thread and reads state. Clearing
`state.set_thread(tenant_id, owner_id, [])` removes the memory; nothing else
needs undoing.

## Escalation

An answer that is neither the refusal sentence nor accompanied by citations is
an ungrounded-output failure. That is the single most important invariant in
this milestone: stop and treat it as a safety defect, not a content bug.

## Known limitations

- No reranking, no query decomposition, no multi-turn resolution. The thread is
  stored but never read back into the answer.
- `bbox` is a zero rectangle on every citation. Real bounding boxes come with
  the reader work in M1.
- Latency is asserted against an in-process state, not a database.
