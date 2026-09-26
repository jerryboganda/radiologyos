# Runbook — knowledge graph and past-paper topic weights

ADR 0016. Migration `20260926_0008`. Task `radbrain.knowledge_extract`.

## Normal flow

1. An upload finishes its ingest vision pass; the worker marks the job step
   `knowledge_extraction` pending and queues `radbrain.knowledge_extract` in
   `notes` mode (set `KNOWLEDGE_AUTO_EXTRACT=0` on the worker to disable).
2. For past papers (IMM, FCPS-II theory, TOACS, FRCR), request past-paper mode:

   ```http
   POST /v1/knowledge/sources/{source_id}/extract
   {"mode": "past_paper", "exam_target": "imm", "year": 2019}
   ```

   `exam_target` and `year` are optional overrides for what the page shows.
3. Review suggested weights with `GET /v1/knowledge/topic-weights?exam_target=imm`.
   Each row has `basis` (counts, papers, years, method). Approve with
   `POST /v1/knowledge/topic-weights/approve {"exam_target": "imm"}` (optionally
   `weight_ids`). Recomputation clears approval on any weight whose value changed.

## Status and resume

- Step status: `GET /v1/library/sources/{id}` → `steps[knowledge_extraction]`
  (`output_ref` like `notes:chunks:12,claims:40,rejected:3,failed:0`).
- Per-unit progress is in `knowledge_runs`; re-requesting extraction only
  processes new, changed, or failed chunks/pages. A usage-limit pause sets the
  step back to `pending` and re-queues after `INGEST_DEFER_SECONDS`.
- No model transport on the worker → step `skipped` (`no_model_transport`).

## Conflicts

`GET /v1/knowledge/conflicts` lists open conflicts with both claims, spans, and
citations side by side. Resolve with
`POST /v1/knowledge/conflicts/{id}/resolve {"resolution": "...", "preferred_claim_id": "..."}`;
the preferred claim becomes `active`, the other `superseded`; omit the
preference to keep both `active`. Every resolution is audited.

## Review queue

Curriculum mappings with confidence < 0.7 are stored with `status = 'review'`
in `curriculum_mappings`. The owner reviews them at `/knowledge/review`
(`GET /v1/knowledge/mappings?status=review`): **accept** keeps the code,
**reject** discards it, and **re-code** (`POST /v1/knowledge/mappings/{id}/decide`
with `{"decision": "code", "curriculum_code": ...}`) moves it to another system
code from `GET /v1/knowledge/curriculum/systems` (unknown codes are refused).
Re-coding onto a code the same unit already has merges into that row. Only the
source's uploader sees or decides a mapping; each decision is audited as
`knowledge.mapping_decided` with the decision and code only.

## Logging

Workers log source ids, unit hashes, agent names, and counts only; never chunk
text, spans, or prompts (hard rule 4).
