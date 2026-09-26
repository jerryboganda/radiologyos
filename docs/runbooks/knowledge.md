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
with `{"decision": "code", "curriculum_code": ...}`) moves it to any curriculum
node: a system, topic, or subtopic id from
`GET /v1/knowledge/curriculum/candidates` (unknown ids are refused). The system
is stored in `curriculum_code` and the node in `curriculum_node_id` (ADR 0023).
Re-coding onto a code the same unit already has merges into that row. Only the
source's uploader sees or decides a mapping; each decision is audited as
`knowledge.mapping_decided` with the decision and code only.

## Curriculum tree and approval (ADR 0023)

The draft tree is `packages/curriculum/radiology/`: `pack.json` holds the
version, sources, and system file order, and each system file nests topics and
subtopics with exam tags. Edit these files to change the tree. The loader
validates the hierarchy, code prefixes, and tag subsets
(`apps/api/tests/test_curriculum_pack.py`). Never rename an existing system code.

1. Open `/knowledge/curriculum` (`GET /v1/knowledge/curriculum?exam_target=imm`)
   and browse the tree by exam.
2. As the owner or an admin (`org_admin`/`superadmin`), approve or reject the
   version shown (`POST /v1/knowledge/curriculum/decision` with
   `{"decision": "approved"|"rejected", "content_hash": ..., "notes": ...}`). A
   rejection needs a note. A student gets 403.
3. The decision is a new `curriculum_reviews` row and a
   `knowledge.curriculum_approved|rejected` audit row. It holds only while the
   pack hash is unchanged: any edit to the tree shows as `pending` again (409 if
   the page was stale).

Weights are separate. Approve them per exam on `/knowledge` once past papers
have been read. Since `paper_topics/v3`, topic-level weights use tree node ids.

## Knowledge depth: notes, duplicates, conflict verdicts (ADR 0030)

After `knowledge_extraction` succeeds in notes mode, the worker queues
`radbrain.knowledge_depth` for the source. Set `KNOWLEDGE_DEPTH_AUTO=0` on the worker
to turn the automatic pass off.

- **Status:** `GET /v1/library/sources/{id}` → `steps[knowledge_depth]`
  (`output_ref` like `conflicts:2,pairs:1,notes:5`). A run makes at most 20 model
  calls, then re-queues itself (`pending`/`continuing`). A usage limit sets
  `pending`/`usage_limit` and resumes after `INGEST_DEFER_SECONDS`. Units already
  done are skipped; each is a `knowledge_runs` row with unit `conflict:<id>`,
  `pair:<a>:<b>` or `note:<concept>:<hash>`. A unit whose model call failed is
  recorded as `skipped` with `model_error` and is not retried automatically.
- **Order:** conflict verdicts, then duplicate resolution, then notes.
- **Notes:** these are written automatically only for concepts with three or more
  of the owner's claims. On any concept page, **Write the note** or **Regenerate
  from claims** (`POST /v1/knowledge/concepts/{id}/note/synthesize`) queues
  `radbrain.concept_note`. That task does nothing when the claims are unchanged. A
  note is `current` while its claims hash matches, and `stale` once claims change.
  **Mark verified** (`POST .../note/verify {"note_id": ...}`) accepts only the
  current draft on a concept with no open conflict; anything else returns 409. It
  is audited as `knowledge.note_verified`.
- **Duplicates:** `/knowledge/review` → *Possible duplicate concepts*
  (`GET /v1/knowledge/merges?status=review`). **Merge them** or **Keep separate**
  (`POST /v1/knowledge/merges/{id}/decide`). *Recent merges* has **Undo merge**
  (`POST /v1/knowledge/merges/{id}/undo`). Undo moves the claims, edges and
  conflicts back and removes only the names the merge added. It returns 409 if the
  survivor was merged again later; undo that merge first. Opening a merged concept
  redirects to its survivor.
- **Conflicts:** each card shows the model verdict (true conflict, both valid in
  context, or same fact), its confidence, and the claims it relied on. A confident
  *context* or *same* verdict closes the conflict with both claims kept. Otherwise
  choose **Trust source A**, **Trust source B** or **Both valid in context**
  (`POST /v1/knowledge/conflicts/{id}/trust {"trust": "a"|"b"|"both", "note": ""}`),
  audited as `knowledge.conflict_trusted`.
- **Models:** all three agents use their route's targets (Claude, medium effort).
  To run Synthesis Mistral-first like bulk ingest, add an `agents:` entry in
  `models.yaml`. That needs the owner's OK.

## Logging

Workers log source ids, unit hashes, agent names, and counts only; never chunk
text, spans, or prompts (hard rule 4).
