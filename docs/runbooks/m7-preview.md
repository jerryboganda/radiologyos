# M7 preview runbook — local mode and portable export

- Status: current, non-release
- Scope: local-model boundary, Markdown export, round-trip provenance
- Gate: `evals/checks/test_m7_portability.py` (slice W, X)
- Related: [M6 preview operations](m6-preview-operations.md), [ADR 0006](../decisions/0006-non-release-preview-mode.md)

## Prerequisites

- A tenant and owner with at least one ingested source for a non-empty export.
- No model download, no local weights, no provider key. Nothing in this
  milestone requires one.

## Local-model mode

`local_mode_status()` is the whole surface:

```json
{"backend": "mock", "certified": false,
 "message": "Local model certification and provider/privacy approval remain release blockers."}
```

`certified` is `false` and the response carries no threshold values. It must
never claim an approved lower threshold, because selecting a model or a
threshold is a human decision with an ADR behind it.

## Export

`markdown_export(state, tenant_id, owner_id)` emits a Markdown document with one
`## <title>` section per source the owner can see, and for every chunk:

```markdown
<chunk text>

Citation: `<source-uuid>` p. <page> block `<block-uuid>`
```

Preamble: `# radbrain preview export` and an explicit
`Synthetic local export. Not a Core Library artifact.`

Export is owner-scoped *and* tenant-scoped, and byte-stable across repeated
calls on unchanged state.

## Verification

```bash
python -m pytest -q evals/checks/test_m7_portability.py
```

The gate asserts: local mode is uncertified and exposes no approved threshold;
the tutor labels itself as the preview route; preview routes are absent from
the contract when disabled; the export is Markdown-shaped with no HTML; **every
citation line parses and resolves back to a real block on a real page**; the
export survives a re-ingest; provenance is re-issued after a delete and
re-ingest under the same idempotency key; export is byte-stable; no other
tenant's identifiers or content appear; an empty tenant still yields a valid
document; only portable Markdown constructs are used; and a second owner
exports only their own sources.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| Export is empty | the owner owns no sources, or all are deleted | check `state.sources` filtered by owner |
| A citation will not parse | the line format changed | the regex is `^Citation: \`(?P<source>uuid)\` p\. N block \`(?P<block>uuid)\`$` |
| Another tenant's id appears in the export | a real isolation failure | stop; see escalation |
| `certified` is anything but `false` | someone set a threshold without an ADR | revert immediately |

## Rollback

Export is read-only. There is nothing to undo. A bad export is fixed by
correcting the underlying source and re-exporting.

## Escalation

Export is a data-egress surface. If it ever returns content the caller should
not see — another tenant, another owner, or a quarantined source — treat it as a
containment failure and stop.

## Known limitations

- Markdown only. There is no Obsidian-compatible graph, no wiki links, no
  round-trip *import* back into the application, and no attachment handling.
- `bbox` is a zero rectangle, so exported citations locate a block but not a
  region on the page.
- Slice Y (mobile wrapper, institution SSO, Core authoring) is not started.
  Each of those needs its own human decision and acceptance evidence, and none
  is simulated here.
- Local mode is a stub. There is no model loading, no evaluation of a local
  model, and no threshold comparison to measure against.
