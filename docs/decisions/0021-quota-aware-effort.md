# 0021 — Quota-aware effort for bulk ingest agents

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0010 (Claude subscription model routes), ADR 0016 (knowledge and weights), ADR 0019 (embedding cost)

**Context.** Every agent runs on Claude Opus 5.5 through the owner's Max 20x
subscription, so tokens drawn by bulk ingest come out of the same usage windows
the owner uses day to day. Reprocessing the library runs `page_parse` once per page
(about 6,900 pages) and `knowledge_extract` plus `topic_classify` once per chunk
(about 5,400 chunks each). In v1 these ran at `medium`, `high`, and `high`.
Thinking tokens are billed as output and effort decides how many are spent, so
these three agents dominate the quota cost of a reprocess.

**Decision.** The owner approved this on 2026-09-26. New prompt versions keep the
text unchanged and only lower the effort:
- `page_parse/v2`: `low` (transcription is perception, not reasoning);
- `knowledge_extract/v2`: `medium`;
- `topic_classify/v2` and `paper_topics/v2`: `low` (labelling).

The model stays Claude Opus 5.5. The loader picks the highest version, and v1
stays as history. The grounding judge, question check, tutor, question
generation, and grading stay at `high`: they are low-volume, and they are where
quality or safety is decided. Before the full reprocess, a 20-page sample is run
and its real token usage is reported to the owner.

**Consequences.** A reprocess should cost well under half the quota it would at
v1 efforts. If the sample shows missed text, figures, or claims, raise the one
affected agent to the next level in a v3. Effort for the four agents is now set
in their prompt files, which override the route default in `models.yaml`.

**Rejected.**
- Claude Sonnet 5 at `xhigh`: its extra thinking tokens would cancel out the
  lower per-token price, and page reading doesn't need deep reasoning.
- Claude Sonnet 5 at `low`: this is the cheapest option, but it is weaker on
  dense radiology slides, and parsing quality is the owner's priority (ADR 0011).
- Lowering the route defaults in `models.yaml` only: the prompt effort would
  override them, so nothing would change.
