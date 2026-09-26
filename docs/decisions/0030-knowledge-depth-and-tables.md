# 0030 — Knowledge depth: Synthesis, Resolver and Conflict agents; tables; re-process

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0010 (model routes), ADR 0012 (library), ADR 0016 (knowledge graph),
  ADR 0018 (data rights), ADR 0019 (embedding cost), ADR 0021 (quota-aware effort),
  ADR 0027 (free-first ingest); completion plan WP-H (G14, G15)

**Decision.** Migration `20260926_0103` (expand-only) adds three tenant tables with
ENABLE+FORCE RLS, grants, a two-tenant runtime-role proof
(`evals/checks/test_knowledge_depth_live.py`) and data-rights entries:
`concept_notes` (per owner and concept, versioned, keyed by the SHA-256 of the
claims it was built from), `concept_merges` (one Resolver decision per unordered
concept pair, with the snapshot that makes a merge reversible) and `source_tables`
(table blocks as rows, CSV and escaped HTML, with the block's bbox and a tsvector).
It adds nullable `concepts.merged_into`, the Conflict agent's verdict columns and
the owner's `trust` choice on `knowledge_conflicts`, and widens the job-step
vocabulary with `knowledge_depth`. After `knowledge_extraction` succeeds in notes
mode the worker queues `radbrain.knowledge_depth` (off with
`KNOWLEDGE_DEPTH_AUTO=0`). It is one visible, resumable step per source, with at
most 20 model calls per run. Each unit (conflict, pair, or concept and claims hash)
is recorded in `knowledge_runs` against the agent and pipeline versions, so a
re-run pays for nothing twice. The pass runs in order:

1. **Conflict agent** (`claim_conflict/v1`, route `reason`, effort medium). It
   labels each open heuristic conflict `conflict`, `context` or `same`, with a
   rationale citing [A]/[B]. A `context`/`same` verdict at 0.80 confidence or more
   closes the conflict with both claims kept. Anything else stays open for the
   owner, who can **trust A**, **trust B**, or keep **both valid in context**
   (`POST /v1/knowledge/conflicts/{id}/trust`, audited).
2. **Resolver** (`concept_resolver/v1`, route `reason`, effort medium). It handles
   unmerged pairs whose best name or alias trigram similarity is 0.80–0.92. A
   `merge` at 0.85 confidence or more is applied. The concept with more claims
   survives; claims, movable edges and conflicts move to it, and it gains the other
   concept's names and keys. The merged concept stays as a redirect. A confident
   `distinct` or `parent_child` is recorded, and anything less confident is queued
   at `/knowledge/review`. Every applied merge can be undone, which removes exactly
   what it added (`/v1/knowledge/merges/*`, audited).
3. **Synthesis** (`concept_synthesis/v1`, route `extract`, effort medium). It
   writes a note from only the owner's active or disputed claims for a concept,
   labelled `C1..Cn`: definition, imaging by modality, differentials with
   discriminators, pearls and pitfalls. Code keeps a sentence only if every label
   it cites was supplied and it is lexically supported by the cited claims: most
   content words present, every number present, and no negation the claims lack.
   Everything else is dropped. A note with no supported sentence is not stored
   (fail closed), and the gateway `accept=` gate falls back when most sentences
   fail. Notes are written automatically for concepts with three or more claims;
   any other concept gets one on request. New versions are `draft`. Only the owner
   can mark the exact current version `verified`, and only while it matches the
   claims and no conflict is open.

**Tables and re-process (G15).** The `extract_tables` step no longer reports
`skipped`. On every chunk pass it rebuilds `source_tables` from `table` blocks with
a deterministic parser for `page_parse`'s `" | "` rows (also Markdown, tab and
space-aligned columns); no model is called. Tables show in the reader and in
search results. `POST /v1/library/sources/{id}/reprocess` is limited to the
uploader and is refused while the job is running. It retries failed pages and
re-queues the source's job: finished steps, parsed pages and knowledge units are
skipped, and unchanged text comes from the embedding cache.

**No new dependencies.** The concept map is a hand-rolled SVG radial layout (1–2
hops, only edges from the owner's sources) whose nodes are focusable links; the
arrow keys move between them, and theme tokens colour it in light and dark. `packages/models/models.yaml` is unchanged, so
the three agents use their route targets (Claude). Adding Mistral-first `agents:`
entries for `concept_synthesis`, as ADR 0027 did for bulk ingest, is left to the
owner.

**Consequences and limits.** The support check is lexical, not a semantic judge.
It can keep a cited sentence that paraphrases its claims loosely, and it can drop a
correct one that paraphrases them heavily. Merges are tenant-wide graph operations.
In a multi-member tenant, erasing one member deletes their merge records, and the
merges they made can then no longer be undone. After a merge, claims are not
compared again for duplicates. Table rows are only as good as the parser's table
text.
