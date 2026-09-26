# 0016 — Durable knowledge graph, curriculum mapping, and past-paper topic weights

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0010 (models), ADR 0011 (personal-first), ADR 0012 (library)

Migration `20260926_0008` adds `concepts`, `claims`, `concept_edges`,
`knowledge_conflicts`, `curriculum_mappings`, `topic_frequencies`,
`topic_weights`, and `knowledge_runs`, each with ENABLE+FORCE RLS and
two-tenant runtime-role proofs (`evals/checks/test_knowledge_live.py`,
`test_knowledge_pipeline_live.py`). The Celery task `radbrain.knowledge_extract`
runs after the ingest vision pass (or on request) in one of two modes. **Notes**
runs `knowledge_extract` (route `extract`, effort high) per chunk of 30+ words;
a claim is stored only if its `evidence_span` is a verbatim substring of the
chunk (whitespace-only differences tolerated), and its citation carries source,
pages, and the block/bbox holding the span. Concepts resolve by normalised name
or alias (UK/US spelling, possessive eponyms, a fixed abbreviation table,
plural keys) or pg_trgm-compatible trigram similarity >= 0.92; 0.80-0.92 stays
a separate concept until a `reason` adjudicator exists. Same-concept claims that
are near-identical merge as supporting citations (`verified` when a second
source agrees); overlapping claims that disagree on a same-unit number,
negation, or an opposed term pair create an open `knowledge_conflicts` row and
mark both claims `disputed`, never overwriting either. `topic_classify` (route
`classify`) maps each chunk to a curriculum system code with a topic; codes
outside the pack are dropped and confidence < 0.7 goes to the review queue.
**Past paper** runs `paper_topics` (route `classify`) per page to count
question topics per exam target (`imm`, `fcps2_theory`, `fcps2_toacs`, `frcr`,
`unknown`) and year, then suggests per-user weights by Laplace-smoothed
normalised frequency (alpha 1, over all curriculum systems, plus observed
topics, per target and `all`). Weights are stored **unapproved**, a changed
weight loses its approval, and only the owner's explicit approval
(`POST /v1/knowledge/topic-weights/approve`, audited) makes them usable; the
curriculum pack's own `exam_weight` stays null. Progress is idempotent per
(source, content hash, agent version, pipeline version) and a subscription
usage limit defers the task. No new dependencies.
